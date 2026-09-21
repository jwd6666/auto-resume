from app.db.database import init_db, engine
from sqlalchemy import inspect, text

init_db()
insp = inspect(engine)
cols = [c['name'] for c in insp.get_columns('model_templates')]
print('columns:', cols)
if 'api_key' not in cols:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE model_templates ADD COLUMN api_key VARCHAR(512) DEFAULT ''"))
        conn.commit()
    print('Added api_key column')
else:
    print('api_key already exists')
