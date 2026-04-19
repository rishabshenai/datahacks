import boto3
s3 = boto3.client('s3', region_name='us-west-2')
s3.download_file('aegis-ocean-data', 'mooring_replay.csv', 'mooring_replay.csv')
s3.download_file('aegis-ocean-data', 'isolation_forest.pkl', 'isolation_forest.pkl')
print("Downloaded")
