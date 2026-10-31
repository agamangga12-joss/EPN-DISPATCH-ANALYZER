"""store master vehicle class tags as integers

Revision ID: 0006_vehicle_class_integer
Revises: 0005_default_tag_type_rules
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_vehicle_class_integer"
down_revision = "0005_default_tag_type_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "master_mt",
        "vehicle_type_tag",
        existing_type=sa.String(length=80),
        type_=sa.Integer(),
        postgresql_using="""
            CASE
                WHEN vehicle_type_tag::text ~ '^[0-9]+(\\.0+)?$'
                    THEN vehicle_type_tag::numeric::integer
                ELSE NULL
            END
        """,
    )
    op.alter_column(
        "master_spbu",
        "vehicle_type_tag",
        existing_type=sa.String(length=80),
        type_=sa.Integer(),
        postgresql_using="""
            CASE
                WHEN vehicle_type_tag::text ~ '^[0-9]+(\\.0+)?$'
                    THEN vehicle_type_tag::numeric::integer
                ELSE NULL
            END
        """,
    )


def downgrade() -> None:
    op.alter_column("master_spbu", "vehicle_type_tag", existing_type=sa.Integer(), type_=sa.String(length=80))
    op.alter_column("master_mt", "vehicle_type_tag", existing_type=sa.Integer(), type_=sa.String(length=80))
