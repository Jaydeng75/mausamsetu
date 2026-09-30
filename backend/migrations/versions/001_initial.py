"""Versioned metadata, reviews, replay jobs, and audit events."""
from alembic import op
import sqlalchemy as sa
revision='001'
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('records',sa.Column('id',sa.String(160),primary_key=True),sa.Column('kind',sa.String(40),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_records_kind','records',['kind'])
def downgrade():
    op.drop_index('ix_records_kind',table_name='records');op.drop_table('records')
