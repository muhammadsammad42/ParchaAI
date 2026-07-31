
import sys
from pathlib import Path
import pandas as pd
import re

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def clean_text_field(value: str) -> str:
    """Clean text fields by removing excess whitespace and newlines.
    
    Parameters
    ----------
    value : str
        The text value to clean
    
    Returns
    -------
    str
        Cleaned text with normalized whitespace
    """
    if pd.isna(value):
        return "unread"
    
    # Convert to string
    text = str(value).strip()
    
    # Replace multiple whitespaces/newlines with single space
    text = re.sub(r'\s+', ' ', text)
    
    # Remove trailing/leading commas and spaces
    text = text.strip(' ,')
    
    return text if text else "unread"


def clean_drug_reference_db(
    input_path: Path = None,
    output_path: Path = None,
    verbose: bool = True
) -> pd.DataFrame:
    
    # Set default paths
    if input_path is None:
        # Assume we're in datasets/ directory
        script_dir = Path(__file__).parent
        input_path = script_dir / "raw_drug_database.csv"
        
        # Check if file exists in parent data directory (your current structure)
        if not input_path.exists():
            input_path = script_dir.parent / "data" / "raw_drug_database.csv"
    
    if output_path is None:
        output_path = Path(__file__).parent / "drug_reference_db.csv"
    
    if verbose:
        print("=" * 70)
        print("ParchaAI Drug Reference Database Cleaning Utility")
        print("=" * 70)
        print(f"Input:  {input_path}")
        print(f"Output: {output_path}")
        print()
    
    # Check if input exists
    if not input_path.exists():
        raise FileNotFoundError(
            f"Input file not found: {input_path}\n"
            f"Please ensure the raw drug database exists at this location."
        )
    
    # Load the dataset
    if verbose:
        print("Step 1/6: Loading dataset...")
    df = pd.read_csv(input_path, encoding='utf-8-sig')
    original_count = len(df)
    if verbose:
        print(f"Loaded {original_count} rows, {len(df.columns)} columns")
    
    # Step 1: Remove Image URL and review columns
    if verbose:
        print("\nStep 2/6: Removing Image URL and review columns...")
    
    columns_to_remove = [
        'Image URL',
        'Excellent Review %',
        'Average Review %',
        'Poor Review %'
    ]
    
    # Only remove columns that exist
    existing_columns_to_remove = [col for col in columns_to_remove if col in df.columns]
    df = df.drop(columns=existing_columns_to_remove, errors='ignore')
    
    if verbose:
        print(f"Removed {len(existing_columns_to_remove)} columns: {existing_columns_to_remove}")
        print(f"Remaining columns: {list(df.columns)}")
    
    # Step 2: Replace missing values with "unread"
    if verbose:
        print("\nStep 3/6: Replacing missing values with 'unread'...")
    
    missing_before = df.isna().sum().sum()
    df = df.fillna("unread")
    
    if verbose:
        print(f"Replaced {missing_before} missing values")
    
    # Step 3: Remove duplicate medicines based on name
    if verbose:
        print("\nStep 4/6: Removing duplicate medicines...")
    
    if 'Medicine Name' in df.columns:
        # Keep first occurrence of each medicine
        df = df.drop_duplicates(subset=['Medicine Name'], keep='first')
        duplicates_removed = original_count - len(df)
        
        if verbose:
            print(f"Removed {duplicates_removed} duplicate rows")
            print(f"Unique medicines remaining: {len(df)}")
    else:
        if verbose:
            print("Warning: 'Medicine Name' column not found, skipping deduplication")
    
    # Step 4: Clean 'Uses' and 'Side_effects' fields
    if verbose:
        print("\nStep 5/6: Cleaning 'Uses' and 'Side_effects' fields...")
    
    for field in ['Uses', 'Side_effects']:
        if field in df.columns:
            df[field] = df[field].apply(clean_text_field)
            if verbose:
                print(f"Cleaned '{field}' column")
        else:
            if verbose:
                print(f"Warning: '{field}' column not found")
    
    # Step 5: Clean other text columns
    if verbose:
        print("\nStep 6/6: Cleaning remaining text columns...")
    
    # Clean all string columns
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].apply(clean_text_field)
    
    if verbose:
        print(f"Cleaned all text columns")
    
    # Save the cleaned dataset
    if verbose:
        print(f"\nSaving cleaned dataset to: {output_path}")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding='utf-8')
    
    if verbose:
        print(f"Saved successfully!")
        print()
        print("=" * 70)
        print("Summary:")
        print("=" * 70)
        print(f"  Original rows:      {original_count}")
        print(f"  Cleaned rows:       {len(df)}")
        print(f"  Rows removed:       {original_count - len(df)}")
        print(f"  Final columns:      {len(df.columns)}")
        print(f"  Column names:       {', '.join(df.columns)}")
        print("=" * 70)
        print()
        print("Drug reference database cleaned successfully!")
        print()
    
    return df


def verify_cleaned_database(db_path: Path = None, sample_size: int = 5) -> None:
    """Verify the cleaned database and display sample records.
    
    Parameters
    ----------
    db_path : Path, optional
        Path to the cleaned database. If None, uses default path.
    sample_size : int, optional
        Number of sample records to display, by default 5
    """
    if db_path is None:
        db_path = Path(__file__).parent / "drug_reference_db.csv"
    
    if not db_path.exists():
        print(f"Cleaned database not found at: {db_path}")
        return
    
    print("=" * 70)
    print("Cleaned Database Verification")
    print("=" * 70)
    print(f"File: {db_path}")
    print()
    
    df = pd.read_csv(db_path, encoding='utf-8')
    
    print(f"Total records: {len(df)}")
    print(f"Columns: {list(df.columns)}")
    print()
    
    # Check for missing values
    missing = df.isna().sum()
    print("Missing values per column:")
    for col, count in missing.items():
        print(f"  {col}: {count}")
    print()
    
    # Check for "unread" placeholders
    unread_counts = {}
    for col in df.columns:
        unread_count = (df[col] == "unread").sum()
        if unread_count > 0:
            unread_counts[col] = unread_count
    
    if unread_counts:
        print("'unread' placeholder counts:")
        for col, count in unread_counts.items():
            print(f"  {col}: {count}")
        print()
    
    # Display sample records
    print(f"Sample records (first {sample_size}):")
    print("=" * 70)
    print(df.head(sample_size).to_string())
    print("=" * 70)
    print()
    print("Verification complete!")


if __name__ == "__main__":
    """Run the cleaning utility when executed as a script."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Clean the ParchaAI drug reference database"
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Path to input (raw) drug database CSV"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path to save cleaned database CSV"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify the cleaned database after processing"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output"
    )
    
    args = parser.parse_args()
    
    try:
        # Clean the database
        df = clean_drug_reference_db(
            input_path=args.input,
            output_path=args.output,
            verbose=not args.quiet
        )
        
        if args.verify:
            verify_cleaned_database(db_path=args.output)
        
        sys.exit(0)
    
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
