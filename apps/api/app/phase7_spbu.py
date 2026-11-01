"""Joint timing of selected loading bays, physical MT trips and SPBU unloading."""
from collections import defaultdict
from datetime import timedelta, timezone
import math
from time import perf_counter
from ortools.sat.python import cp_model
from .phase7_constants import constraint_is_hard, constraint_is_soft, constraint_penalty, constraint_rule


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def schedule_spbu(trips, bay_result, bays, parameters, day_start, depot_close, deadline):
    if not constraint_rule(parameters,"spbu_no_overlap").get("enabled",True):
        return bay_result
    assignments = {row["trip_index"]: row for row in bay_result.get("assignments", [])}
    resources = defaultdict(list)
    for index in assignments:
        for seq, stop in enumerate(trips[index].get("stops", [])):
            resources[str(stop["loading_order"]["spbu_id"])].append((index, seq))
    reservations = parameters.get("_spbu_reservations", [])
    if not resources:
        return bay_result
    if perf_counter() >= deadline:
        return failed_result(bay_result, assignments, "TIMEOUT")
    model = cp_model.CpModel()
    zero = utc(day_start)
    seconds = lambda value: round((utc(value) - zero).total_seconds())
    horizon = max(3*86400, seconds(depot_close)+3*86400)
    loads, gates, returns, presences, visits, works = {}, {}, {}, {}, {}, {}
    by_bay, by_spbu, by_mt = defaultdict(list), defaultdict(list), defaultdict(list)
    objective, soft_overlaps = [], []
    bay_map = {row["master_bay_id"]: row for row in bays}
    all_overlaps = []
    bay_overlaps = []
    serve_penalty = max(1, constraint_penalty(parameters, "serve_loading_order"))
    for index, assignment in assignments.items():
        trip = trips[index]
        on = model.new_bool_var(f"trip_{index}")
        presences[index] = on
        if constraint_is_hard(parameters,"serve_loading_order"):
            model.add(on == 1)
        objective.append((1-on)*serve_penalty*max(1,len(trip.get("lo_assignments",[]))))
        ready = seconds(trip["vehicle_ready_at_depot"])
        # Retain the selected bay's initial queue/occupancy reservation.
        lower = max(ready, seconds(assignment["loading_start"]))
        load = model.new_int_var(lower,horizon,f"load_{index}")
        duration = max(0,seconds(assignment["loading_finish"])-seconds(assignment["loading_start"]))
        finish = load+duration
        gate = finish+int(parameters.get("gate_process_time",5))*60
        loads[index], gates[index] = load, gate
        by_bay[assignment["master_bay_id"]].append(model.new_optional_interval_var(load,duration,finish,on,f"bay_{index}"))
        bay_overlaps.append((assignment["master_bay_id"],load,finish,on,index,0))
        by_mt[trip["vehicle_id"]].append(index)
        bay = bay_map.get(assignment["master_bay_id"],{})
        for constraint_id,close in [("depot_operating_window",seconds(depot_close)),("bay_operating_window",int(bay.get("operational_end_minutes") or seconds(depot_close)//60)*60)]:
            if constraint_is_soft(parameters,constraint_id):
                late=model.new_bool_var(f"late_{constraint_id}_{index}")
                model.add(gate<=close).only_enforce_if([on,late.Not()])
                objective.append(late*constraint_penalty(parameters,constraint_id))
        if constraint_is_hard(parameters,"depot_operating_window"):
            model.add(gate <= seconds(depot_close)).only_enforce_if(on)
        if constraint_is_hard(parameters,"bay_operating_window"):
            close = int(bay.get("operational_end_minutes") or seconds(depot_close)//60)*60
            model.add(gate <= close).only_enforce_if(on)
        timing = trip.get("trip_timing") or {}
        events = timing.get("events",[])
        last = gate
        stops = trip.get("stops",[])
        for seq, stop in enumerate(stops):
            order=stop["loading_order"]
            if events:
                elapsed=sum(e["end_offset_seconds"]-e["start_offset_seconds"] for e in events
                            if (e.get("leg")==seq and e["kind"] in {"DRIVING","BREAK"}) or (seq==0 and e["kind"]=="REFUELING"))
            else:
                elapsed=int(stop.get("leg_seconds",0))
            arrival=model.new_int_var(0,horizon,f"arrival_{index}_{seq}")
            start=model.new_int_var(0,horizon,f"unload_{index}_{seq}")
            end=model.new_int_var(0,horizon,f"unloaded_{index}_{seq}")
            service=max(0,round((utc(stop["departure"])-utc(stop.get("unloading_start",stop["arrival"]))).total_seconds()))
            model.add(arrival == last+elapsed).only_enforce_if(on)
            model.add(start >= arrival).only_enforce_if(on)
            model.add(end == start+service).only_enforce_if(on)
            wait=model.new_int_var(0,horizon,f"wait_{index}_{seq}")
            model.add(wait == start-arrival).only_enforce_if(on)
            model.add(wait == 0).only_enforce_if(on.Not())
            if constraint_is_hard(parameters,"spbu_time_window"):
                if order.get("time_window_start_minutes") is not None:
                    model.add(start >= int(order["time_window_start_minutes"])*60).only_enforce_if(on)
                if order.get("time_window_end_minutes") is not None:
                    model.add(start <= int(order["time_window_end_minutes"])*60).only_enforce_if(on)
            elif constraint_is_soft(parameters,"spbu_time_window"):
                for boundary,sign in [(order.get("time_window_start_minutes"),-1),(order.get("time_window_end_minutes"),1)]:
                    if boundary is not None:
                        violation=model.new_bool_var(f"window_{index}_{seq}_{sign}")
                        model.add(sign*(start-int(boundary)*60) <= 0).only_enforce_if([on,violation.Not()])
                        objective.append(violation*constraint_penalty(parameters,"spbu_time_window"))
            resource=str(order["spbu_id"])
            interval=model.new_optional_interval_var(start,service,end,on,f"spbu_{index}_{seq}")
            by_spbu[resource].append(interval)
            all_overlaps.append((resource,start,end,on,index,seq))
            visits[index,seq]=(arrival,start,end,wait,service,elapsed)
            objective.append(wait*max(1,round(float(parameters.get("queue_cost",1000))/60)))
            last=end
        if events:
            back=sum(e["end_offset_seconds"]-e["start_offset_seconds"] for e in events if e.get("leg")==len(stops) and e["kind"] in {"DRIVING","BREAK"})
        elif stops:
            base_gate=utc(trip.get("preliminary_gate_out",trip["gate_out"]))
            back=max(0,round((utc(trip["estimated_return_depot"])-utc(trip["gate_out"])).total_seconds())-round((utc(stops[-1]["departure"])-base_gate).total_seconds()))
        else:
            back=0
        returned=model.new_int_var(0,horizon,f"return_{index}")
        model.add(returned == last+back).only_enforce_if(on)
        model.add(returned == 0).only_enforce_if(on.Not())
        returns[index]=returned
        work=model.new_int_var(0,horizon,f"work_{index}")
        model.add(work == returned-load).only_enforce_if(on)
        model.add(work == 0).only_enforce_if(on.Not())
        work_minutes=model.new_int_var(0,horizon//60+1,f"work_minutes_{index}")
        model.add_division_equality(work_minutes,work+59,60)
        works[index]=work_minutes
        if constraint_is_hard(parameters,"vehicle_working_time"):
            model.add(work_minutes <= int(trip.get("working_time_remaining_before_trip",horizon//60))).only_enforce_if(on)
        # Objective includes waiting/working cost; a small completion tie-breaker
        # prevents shifting all trips to the end of the horizon.
        objective.extend([work*max(1,round(float(parameters.get("cost_per_operating_hour",50000))/3600)),returned])
        model.add_hint(load,lower)
    for ids in by_mt.values():
        ids.sort(key=lambda i:int(trips[i]["trip_number"]))
        if constraint_is_hard(parameters,"vehicle_working_time"):
            model.add(sum(works[i] for i in ids) <= int(trips[ids[0]].get("working_time_remaining_before_trip",horizon//60)))
        for left,right in zip(ids,ids[1:]):
            model.add(loads[right] >= returns[left]+int(parameters.get("mt_turnaround_buffer_minutes",30))*60).only_enforce_if([presences[left],presences[right]])
            model.add(presences[right] <= presences[left])
    if constraint_is_hard(parameters,"bay_no_overlap"):
        for intervals in by_bay.values(): model.add_no_overlap(intervals)
    reserved_by_spbu=defaultdict(list)
    for reservation in reservations:
        reserved_by_spbu[str(reservation["spbu_id"])].append((int(reservation["start_seconds"]),int(reservation["end_seconds"])))
    merged_reservations=[]
    for resource,windows in reserved_by_spbu.items():
        merged=[]
        for start,end in sorted(windows):
            if end<=start: continue
            if merged and start<=merged[-1][1]: merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
            else: merged.append((start,end))
        merged_reservations.extend((resource,start,end) for start,end in merged)
    for number,(resource,start,end) in enumerate(merged_reservations):
        by_spbu[resource].append(model.new_fixed_size_interval_var(start,end-start,f"reserved_{number}"))
        all_overlaps.append((resource,start,end,model.new_constant(1),None,number))
    def soft_pairs(rows,constraint_id):
        for n,left in enumerate(rows):
            for right in rows[n+1:]:
                if left[0]!=right[0] or (left[4] is None and right[4] is None): continue
                before,after,violation=[model.new_bool_var(f"order_{constraint_id}_{n}_{len(soft_overlaps)}_{k}") for k in range(3)]
                model.add(left[2] <= right[1]).only_enforce_if(before)
                model.add(right[2] <= left[1]).only_enforce_if(after)
                model.add_bool_or([before,after,violation,left[3].Not(),right[3].Not()])
                objective.append(violation*constraint_penalty(parameters,constraint_id))
                soft_overlaps.append((violation,left,right,constraint_id))
    if constraint_is_hard(parameters,"spbu_no_overlap"):
        for intervals in by_spbu.values(): model.add_no_overlap(intervals)
    else:
        soft_pairs(all_overlaps,"spbu_no_overlap")
    if constraint_is_soft(parameters,"bay_no_overlap"):
        soft_pairs(bay_overlaps,"bay_no_overlap")
    model.minimize(sum(objective))
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=max(0.01,deadline-perf_counter())
    solver.parameters.num_search_workers=max(1,min(8,int(parameters.get("bay_cp_sat_workers",8))))
    status=solver.solve(model)
    if status not in {cp_model.OPTIMAL,cp_model.FEASIBLE}:
        return failed_result(bay_result,assignments,"INFEASIBLE" if status==cp_model.INFEASIBLE else "TIMEOUT")
    actual_ready={}
    for ids in by_mt.values():
        ids.sort(key=lambda i:int(trips[i]["trip_number"]))
        available=utc(trips[ids[0]].get("physical_vehicle_ready_at_depot",trips[ids[0]]["vehicle_ready_at_depot"]))
        for index in ids:
            if solver.value(presences[index]):
                actual_ready[index]=available
                available=zero+timedelta(seconds=solver.value(returns[index])+int(parameters.get("mt_turnaround_buffer_minutes",30))*60)
    new_assignments=[]
    dropped=set(bay_result.get("dropped_trip_indexes",[]))
    for index,assignment in assignments.items():
        if not solver.value(presences[index]):
            dropped.add(index);continue
        trip=trips[index]
        shift=zero+timedelta(seconds=solver.value(loads[index]))-utc(assignment["loading_start"])
        for key in ("loading_start","loading_finish","gate_out"):
            assignment[key]=utc(assignment[key])+shift
        assignment["vehicle_ready_at_depot"]=actual_ready[index]
        trip["physical_vehicle_ready_at_depot"]=actual_ready[index]
        assignment["queue_start"]=assignment["loading_start"]
        assignment["queue_minutes"]=0
        trip.update(assignment)
        trip["constraint_violations"]=[row for row in trip.get("constraint_violations",[]) if row.get("constraint_id") not in {"spbu_no_overlap","spbu_time_window","bay_no_overlap","bay_operating_window","depot_operating_window"}]
        bay=bay_map.get(assignment["master_bay_id"],{})
        for constraint_id,close in [("depot_operating_window",seconds(depot_close)),("bay_operating_window",int(bay.get("operational_end_minutes") or seconds(depot_close)//60)*60)]:
            if constraint_is_soft(parameters,constraint_id) and seconds(trip["gate_out"])>close:
                trip["constraint_violations"].append({"constraint_id":constraint_id,"penalty":constraint_penalty(parameters,constraint_id),"entity":trip["vehicle_id"]})
        trip["estimated_return_depot"]=zero+timedelta(seconds=solver.value(returns[index]))
        trip["working_start_at"]=assignment["loading_start"]
        trip["operating_minutes"]=math.ceil((trip["estimated_return_depot"]-trip["working_start_at"]).total_seconds()/60)
        gate=utc(trip["gate_out"])
        clock=trip.get("trip_timing") or {}
        prior_events=clock.get("events",[])
        new_events=[];arrivals=[];departures=[];queues=[];cursor=0
        for seq,stop in enumerate(trip.get("stops",[])):
            arrival,start,end,wait,service,elapsed=visits[index,seq]
            at,begin,finish=[zero+timedelta(seconds=solver.value(v)) for v in (arrival,start,end)]
            for event in prior_events:
                if (event.get("leg")==seq and event["kind"] in {"DRIVING","BREAK"}) or (seq==0 and event["kind"]=="REFUELING"):
                    duration=event["end_offset_seconds"]-event["start_offset_seconds"]
                    new_events.append({**event,"start_offset_seconds":cursor,"end_offset_seconds":cursor+duration});cursor+=duration
            if not prior_events and elapsed:
                new_events.append({"kind":"DRIVING","leg":seq,"start_offset_seconds":cursor,"end_offset_seconds":cursor+elapsed});cursor+=elapsed
            queue=solver.value(wait)
            if queue:
                new_events.append({"kind":"SPBU_QUEUE","leg":seq,"start_offset_seconds":cursor,"end_offset_seconds":cursor+queue});cursor+=queue
            new_events.append({"kind":"SERVICE","leg":seq,"start_offset_seconds":cursor,"end_offset_seconds":cursor+service});cursor+=service
            # Stops remain relative to preliminary gate-out until persistence.
            base=utc(trip.get("preliminary_gate_out",gate));delta=gate-base
            order=stop["loading_order"]
            start_seconds=round((begin-zero).total_seconds())
            if constraint_is_soft(parameters,"spbu_time_window") and ((order.get("time_window_start_minutes") is not None and start_seconds<int(order["time_window_start_minutes"])*60) or (order.get("time_window_end_minutes") is not None and start_seconds>int(order["time_window_end_minutes"])*60)):
                trip["constraint_violations"].append({"constraint_id":"spbu_time_window","penalty":constraint_penalty(parameters,"spbu_time_window"),"entity":order["loading_order_id"]})
            stop.update(arrival=at-delta,unloading_start=begin-delta,departure=finish-delta,spbu_queue_seconds=queue,service_minutes=service/60)
            arrivals.append(round((at-gate).total_seconds()));departures.append(round((finish-gate).total_seconds()))
            queues.append({"spbu_id":stop["loading_order"]["spbu_id"],"sequence":seq+1,"arrival_offset_seconds":round((at-gate).total_seconds()),"unloading_start_offset_seconds":round((begin-gate).total_seconds()),"departure_offset_seconds":round((finish-gate).total_seconds()),"queue_seconds":queue})
        for event in prior_events:
            if event.get("leg")==len(trip.get("stops",[])) and event["kind"] in {"DRIVING","BREAK"}:
                duration=event["end_offset_seconds"]-event["start_offset_seconds"]
                new_events.append({**event,"start_offset_seconds":cursor,"end_offset_seconds":cursor+duration});cursor+=duration
        tail=max(0,round((trip["estimated_return_depot"]-gate).total_seconds())-cursor)
        if not prior_events and tail:
            new_events.append({"kind":"DRIVING","leg":len(trip.get("stops",[])),"start_offset_seconds":cursor,"end_offset_seconds":cursor+tail});cursor+=tail
        trip["spbu_queue_seconds"]=sum(row["queue_seconds"] for row in queues)
        trip["trip_timing"]={**clock,"events":new_events,"arrival_offsets":arrivals,"departure_offsets":departures,"total_seconds":round((trip["estimated_return_depot"]-gate).total_seconds()),"spbu_visits":queues,"spbu_queue_seconds":trip["spbu_queue_seconds"]}
        new_assignments.append(assignment)
    for violation,left,right,constraint_id in soft_overlaps:
        value = lambda item: item if isinstance(item,int) else solver.value(item)
        overlap = min(value(left[2]),value(right[2])) > max(value(left[1]),value(right[1]))
        if overlap and solver.value(left[3]) and solver.value(right[3]):
            live = [row for row in (left,right) if row[4] is not None and row[4] not in dropped]
            for row in live:
                trips[row[4]].setdefault("constraint_violations",[]).append({"constraint_id":constraint_id,"penalty":constraint_penalty(parameters,constraint_id)/len(live),"entity":row[0]})
    return {**bay_result,"assignments":new_assignments,"dropped_trip_indexes":sorted(dropped),"dropped_trip_reasons":{**bay_result.get("dropped_trip_reasons",{}),**{i:"SPBU_CONGESTION" for i in dropped if i in assignments}},"spbu_engine":"OR_TOOLS_CP_SAT","spbu_status":solver.status_name(status)}


def failed_result(bay_result,assignments,status):
    dropped=set(bay_result.get("dropped_trip_indexes",[]))|set(assignments)
    return {**bay_result,"solver_status":status,"assignments":[],"dropped_trip_indexes":sorted(dropped),"dropped_trip_reasons":{**bay_result.get("dropped_trip_reasons",{}),**{i:"SPBU_CONGESTION" for i in assignments}},"spbu_engine":"OR_TOOLS_CP_SAT","spbu_status":status}
