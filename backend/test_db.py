from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
engine = create_engine(f'mysql+pymysql://sonika_user:{quote_plus("sonika@sql")}@202.47.117.220:3306/sonika_erp')
with engine.connect() as conn:
    res = conn.execute(text('DESCRIBE lms_units'))
    for row in res.fetchall():
        print(row)
