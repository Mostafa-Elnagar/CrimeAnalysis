import pandas as pd
import numpy as np
from sqlalchemy import create_engine, types, text, inspect
from tqdm import tqdm
import config
import re
from warnings import filterwarnings
filterwarnings('ignore')

# -------------------- CONFIG --------------------
CSV_PATH = "Crimes_-_2001_to_Present.csv"

DB_CONNECTION_STRING = (
    f"mssql+pyodbc://{config.DB_USER}:{config.DB_PASSWORD}@{config.DB_SERVER}/"
    f"{config.DB_NAME}?driver={config.DB_DRIVER.replace(' ', '+')}"
)

engine = create_engine(DB_CONNECTION_STRING, fast_executemany=True)

CHUNKSIZE = 100_000


# Function to enable IDENTITY_INSERT
def enable_identity_insert(engine, table_name):
    with engine.connect() as conn:
        conn.execute(text(f"SET IDENTITY_INSERT {table_name} ON"))

# Function to disable IDENTITY_INSERT
def disable_identity_insert(engine, table_name):
    with engine.connect() as conn:
        conn.execute(text(f"SET IDENTITY_INSERT {table_name} OFF"))

# -------------------- BUILD DIMENSION --------------------
def build_dim(df, cols, table_name, engine, start_id=1):
    dim_name = "_".join(table_name.split('_')[1:])
    col_names = [col["name"] for col in inspect(engine).get_columns(table_name)]
    dim = df[cols].drop_duplicates().reset_index(drop=True)
    end_id = len(dim) + start_id
    dim.columns = col_names[1:]
    dim[f'{dim_name}_id'] = np.arange(start_id, end_id)
    enable_identity_insert(engine, table_name )
    dim.to_sql(table_name, engine, index=False, if_exists='append')
    disable_identity_insert(engine, table_name)
    return dim, end_id

# -------------------- BUILD DATE DIM --------------------
def build_date_dim(df, start_id=1):
    df['date_only'] = pd.to_datetime(df['Date']).dt.date
    dim = pd.DataFrame(df['date_only'].unique(), columns=['full_date'])
    end_id = len(dim) + start_id
    dim['date_id'] = np.arange(start_id, end_id)
    dim['year'] = pd.to_datetime(dim['full_date']).dt.year
    dim['month'] = pd.to_datetime(dim['full_date']).dt.month
    dim['day'] = pd.to_datetime(dim['full_date']).dt.day
    dim['day_of_week'] = pd.to_datetime(dim['full_date']).dt.day_name()
    dim['is_weekend'] = dim['day_of_week'].isin(['Saturday', 'Sunday']).astype(int)
    enable_identity_insert(engine, 'dim_date')
    dim.to_sql("dim_date", engine, index=False, if_exists="append")
    disable_identity_insert(engine, 'dim_date')
    return dim, end_id

# # -------------------- FIRST CHUNK (Build Dimensions) --------------------
# reader = pd.read_csv(CSV_PATH, chunksize=CHUNKSIZE, parse_dates=["Date", "Updated On"], low_memory=False)
# first_chunk = next(reader)

# print("Loading dimensions...")
# dim_date = build_date_dim(first_chunk)
# dim_crime_type = build_dim(first_chunk, ['IUCR', 'Primary Type', 'Description', 'FBI Code'], 'dim_crime_type', engine)
# dim_location = build_dim(first_chunk, ['Block', 'Ward', 'Community Area', 'Location Description', 'Latitude', 'Longitude'], 'dim_location', engine)
# print("Dimensions Loaded.")

# -------------------- RESET READER --------------------
def normalize_column_names(df):
    df.columns = [
        re.sub(r'\W+', '_', col.strip().lower())  # Replace non-alphanumeric with underscore
        for col in df.columns
    ]
    return df

# Define data types for supported types
dtype_mapping = {
    "ID": "Int64",  
    "Case Number": "string",
    "Block": "string",
    "IUCR": "string",
    "Primary Type": "string",
    "Description": "string",
    "Location Description": "string",
    "Beat": "string",
    "District": "string",
    "Ward": "string",
    "Community Area": "string",
    "FBI Code": "string",
    "X Coordinate": "Int64",
    "Y Coordinate": "Int64",
    "Year": "Int64",
    "Latitude": "float64",
    "Longitude": "float64",
    "Location": "string"
}

               
reader = pd.read_csv(CSV_PATH, chunksize=CHUNKSIZE, dtype=dtype_mapping, parse_dates=["Date"], low_memory=False)

# -------------------- FACT LOAD --------------------
print("Loading fact table into SQL Server...")
start_date_id, start_location_id, start_crime_type_id = 1, 1, 1
for chunk in tqdm(reader):
    print("Loading dimensions...")
    dim_date, start_date_id = build_date_dim(chunk, start_date_id)
    dim_crime_type, start_crime_type_id = build_dim(chunk, ['IUCR', 'Primary Type', 'Description', 'FBI Code'], 'dim_crime_type', engine, start_crime_type_id)
    dim_location, start_location_id = build_dim(chunk, ['Block', 'Ward', 'Community Area', 'Location Description', 'Latitude', 'Longitude'], 'dim_location', engine, start_location_id)

    print("Dimensions Loaded.")

    print("Merging ...")
    chunk_length = len(chunk)
    print(f"chunk size: {len(chunk)}")
    cols = [
        'id', 'case_number', 'date_id', 'location_id',
        'crime_type_id', "arrest", "domestic", 'beat', 'district'
    ]
    chunk = normalize_column_names(chunk)
    chunk['date_only'] = chunk['date'].dt.date
    print("Merging with dim_date...")
    chunk = chunk.merge(dim_date, left_on='date_only', right_on='full_date', how='left')
    print("Merging with dim_location...")
    chunk = chunk.merge(dim_location, on=['longitude', 'latitude', "location_description", 'block', 'ward', 'community_area'], how='left')
    print("Merging with dim_crime_type...")
    chunk = chunk.merge(dim_crime_type, on=['iucr', 'primary_type', 'description', 'fbi_code'], how='left')
    print("Merging completed.")

    fact = chunk[cols]
    print(fact.head())

    assert len(fact) == chunk_length

    print(f"Loading Fact table with {len(fact)} rows.")


    enable_identity_insert(engine, 'fact_crime_incidents')
    fact.to_sql("fact_crime_incidents", engine, index=False, if_exists='append')
    disable_identity_insert(engine, 'fact_crime_incidents')
    print("Fact table loaded.")

print("All data inserted into SQL Server successfully.")
