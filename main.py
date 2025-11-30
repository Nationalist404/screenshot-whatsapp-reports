import datetime as dt

def main():
    now = dt.datetime.utcnow().isoformat()
    print(f"Hello from GitHub Actions! Time (UTC): {now}")

if __name__ == "__main__":
    main()
