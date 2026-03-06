import pandas as pd
import numpy as np
from scipy.stats import skew, mode

# Function to calculate statistics
def calculate_statistics(file_path):
    # Read the CSV file
    df = pd.read_csv(file_path)

    # Initialize a dictionary to store the results
    statistics = {}

    # Loop through each numeric column in the dataframe
    for column in df.select_dtypes(include=[np.number]).columns:
        column_stats = {}
        data = df[column].dropna()  # Remove NaN values
        
        column_stats['mean'] = data.mean()
        column_stats['std_dev'] = data.std()
        column_stats['min'] = data.min()
        column_stats['max'] = data.max()
        column_stats['median'] = data.median()
        column_stats['mode'] = mode(data).mode[0] if not data.mode().empty else None
        column_stats['variance'] = data.var()
        column_stats['skew'] = skew(data)
        column_stats['range'] = data.max() - data.min()
        
        # Store the statistics for this column
        statistics[column] = column_stats

    return statistics

# Path to your CSV file
file_path = 'path_to_your_file.csv'

# Calculate statistics
stats = calculate_statistics(file_path)

# Print the statistics
for column, column_stats in stats.items():
    print(f"Statistics for column '{column}':")
    for stat, value in column_stats.items():
        print(f"  {stat}: {value}")
    print()
