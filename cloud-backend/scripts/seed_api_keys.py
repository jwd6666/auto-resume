import sys
sys.path.insert(0, '.')
from app.db.database import SessionLocal, init_db
from app.db.models import ModelTemplate

init_db()
db = SessionLocal()

keys = {
    1: "c1f9dc5623b948a096c9255173081fd6.RT6zU5fum9YvbnwJ",
    2: "tFzCcgh88ezsVwWZO1hcEBvTKBfjHqAr",
    3: "9178187d2c7e44099b44a31036f2ce52.uegD4fa0rd04pkfX",
    4: "9178187d2c7e44099b44a31036f2ce52.uegD4fa0rd04pkfX",
    5: "CvJoiQgBEAEaHwgBEhsxNzg4NjY5NDUxNTkwNTQ5OTc0QXFmM2VDbmwiGAgDEhQIAxIQYQprUgm1vjsZVDcKKdahXw==",
}

for tid, key in keys.items():
    t = db.get(ModelTemplate, tid)
    if t:
        t.api_key = key
        print(f"Set api_key for template {tid}: {t.display_name}")

db.commit()
db.close()
print("Done!")
