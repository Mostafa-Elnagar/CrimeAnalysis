from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, BigInteger, String, Float, Boolean, Date, DateTime, ForeignKey, text
)
import config


# Connection string to 'master' DB (used to create the target DB)
DB_CONNECTION_STRING_MASTER = (
    f"mssql+pyodbc://{config.DB_USER}:{config.DB_PASSWORD}@{config.DB_SERVER}/"
    f"master?driver={config.DB_DRIVER.replace(' ', '+')}"
)

# -------------------- CREATE DATABASE IF NOT EXISTS --------------------
engine_master = create_engine(
    DB_CONNECTION_STRING_MASTER,
    isolation_level="AUTOCOMMIT",  
    fast_executemany=True
)

with engine_master.connect() as conn:
    conn.execute(text(f"""
        IF EXISTS (SELECT name FROM sys.databases WHERE name = '{config.DB_NAME}')
        BEGIN
            ALTER DATABASE {config.DB_NAME} SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
            DROP DATABASE {config.DB_NAME};
            CREATE DATABASE {config.DB_NAME};
        END
    """))
    print(f"Database '{config.DB_NAME}' created or already exists.")

# -------------------- CONNECT TO TARGET DATABASE --------------------
DB_CONNECTION_STRING_TARGET = (
    f"mssql+pyodbc://{config.DB_USER}:{config.DB_PASSWORD}@{config.DB_SERVER}/"
    f"{config.DB_NAME}?driver={config.DB_DRIVER.replace(' ', '+')}"
)

engine = create_engine(DB_CONNECTION_STRING_TARGET, fast_executemany=True)
metadata = MetaData()

# -------------------- DIMENSION TABLES --------------------
dim_date = Table('dim_date', metadata,
    Column('date_id', Integer, primary_key=True),  # format: YYYYMMDD
    Column('full_date', Date),
    Column('year', Integer),
    Column('month', Integer),
    Column('day', Integer),
    Column('day_of_week', String(10)),
    Column('is_weekend', Boolean)
)

dim_location = Table('dim_location', metadata,
    Column('location_id', Integer, primary_key=True),
    Column('block', String(100)),
    Column('ward', String(10)),
    Column('community_area', String(10)),
    Column('location_description', String(100)),
    Column('latitude', Float),
    Column('longitude', Float)
)

dim_crime_type = Table('dim_crime_type', metadata,
    Column('crime_type_id', Integer, primary_key=True),
    Column('iucr', String(10)),
    Column('primary_type', String(50)),
    Column('description', String(100)),
    Column('fbi_code', String(10))
)

# -------------------- FACT TABLE --------------------
fact_crime_incidents = Table('fact_crime_incidents', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('case_number', String(20)),
    Column('date_id', Integer, ForeignKey('dim_date.date_id')),
    Column('location_id', Integer, ForeignKey('dim_location.location_id')),
    Column('crime_type_id', Integer, ForeignKey('dim_crime_type.crime_type_id')),
    Column('arrest', Boolean),
    Column('domestic', Boolean),
    Column('beat', String(10)),
    Column('district', String(10))
)

# -------------------- CREATE TABLES --------------------
metadata.create_all(engine)
print("✅ Tables created.")

# -------------------- ADD INDEXES --------------------
with engine.connect() as conn:
    print("📦 Creating indexes...")
    conn.execute(text("CREATE INDEX idx_fact_date_id ON fact_crime_incidents(date_id);"))
    conn.execute(text("CREATE INDEX idx_fact_location_id ON fact_crime_incidents(location_id);"))
    conn.execute(text("CREATE INDEX idx_fact_crime_type_id ON fact_crime_incidents(crime_type_id);"))

print(f"✅ Schema initialized and indexed in database '{config.DB_NAME}'.")
