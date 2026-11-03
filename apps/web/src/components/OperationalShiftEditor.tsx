type Shift = { shift_id: string; name: string; start_time: string; end_time: string };

export default function OperationalShiftEditor({ value, onChange }: { value: unknown; onChange: (value: Shift[]) => void }) {
  const shifts: Shift[] = Array.isArray(value) ? value : [];
  function update(index: number, field: keyof Shift, text: string) {
    onChange(shifts.map((shift, i) => i === index ? { ...shift, [field]: text } : shift));
  }
  return <div className="col-span-full grid gap-2 border border-line p-3">
    <strong className="text-sm">Operational Shifts / Batas Gate-Out</strong>
    <p className="text-xs text-slate-500">Waktu mengikuti timezone depot. LO boleh berangkat lebih awal. Batas akhir yang lebih kecil dari jam mulai berarti hari berikutnya. Tanggal LO adalah tanggal mulai shift.</p>
    {shifts.map((shift, index) => <div key={index} className="flex flex-wrap items-end gap-2">
      {([['shift_id', 'Shift ID'], ['name', 'Nama'], ['start_time', 'Mulai'], ['end_time', 'Batas Gate-Out']] as const).map(([field, label]) => <label key={field} className="grid gap-1 text-xs">{label}<input required className="border border-line px-2 py-2" type={field.endsWith('time') ? 'time' : 'text'} value={shift[field]} onChange={event => update(index, field, event.target.value)} /></label>)}
      <button type="button" className="border border-line px-3 py-2 text-xs" onClick={() => onChange(shifts.filter((_, i) => i !== index))}>Hapus shift</button>
    </div>)}
    <button type="button" className="justify-self-start border border-line px-3 py-2 text-xs" onClick={() => onChange([...shifts, { shift_id: '', name: '', start_time: '05:00', end_time: '11:00' }])}>Tambah shift</button>
  </div>;
}
