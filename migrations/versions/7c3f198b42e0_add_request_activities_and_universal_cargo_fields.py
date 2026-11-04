"""add request activities and universal cargo fields

Revision ID: 7c3f198b42e0
Revises: 6a2d81e9b161
Create Date: 2026-11-04 21:22:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7c3f198b42e0'
down_revision = '6a2d81e9b161'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create request_activities table
    op.create_table(
        'request_activities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('delivery_request_id', sa.Integer(), nullable=False),
        sa.Column('booking_id', sa.Integer(), nullable=True),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_role', sa.String(length=30), nullable=True),
        sa.Column('from_status', sa.String(length=50), nullable=True),
        sa.Column('to_status', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['booking_id'], ['drone_bookings.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['delivery_request_id'], ['delivery_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('request_activities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_request_activities_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_request_activities_delivery_request_id'), ['delivery_request_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_request_activities_booking_id'), ['booking_id'], unique=False)

    # 2. Add columns to delivery_requests table
    with op.batch_alter_table('delivery_requests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('request_reference', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('custom_item_name', sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column('package_dimensions', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('package_count', sa.Integer(), server_default='1', nullable=True))
        batch_op.add_column(sa.Column('handling_instructions', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('pickup_contact_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('pickup_contact_phone', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('delivery_contact_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('delivery_contact_phone', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('special_instructions', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('rejection_reason', sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f('ix_delivery_requests_request_reference'), ['request_reference'], unique=True)


def downgrade():
    with op.batch_alter_table('delivery_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_delivery_requests_request_reference'))
        batch_op.drop_column('rejection_reason')
        batch_op.drop_column('special_instructions')
        batch_op.drop_column('delivery_contact_phone')
        batch_op.drop_column('delivery_contact_name')
        batch_op.drop_column('pickup_contact_phone')
        batch_op.drop_column('pickup_contact_name')
        batch_op.drop_column('handling_instructions')
        batch_op.drop_column('package_count')
        batch_op.drop_column('package_dimensions')
        batch_op.drop_column('custom_item_name')
        batch_op.drop_column('request_reference')

    with op.batch_alter_table('request_activities', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_request_activities_booking_id'))
        batch_op.drop_index(batch_op.f('ix_request_activities_delivery_request_id'))
        batch_op.drop_index(batch_op.f('ix_request_activities_created_at'))

    op.drop_table('request_activities')
