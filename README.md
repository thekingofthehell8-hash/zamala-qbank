# Zamala QBank Pro — Streamlit Cloud package

This package is ready for free deployment on Streamlit Community Cloud.

## Files you need in the GitHub repo
- `streamlit_app.py`
- `requirements.txt`
- `enhanced_module_01_exam_001_100.csv`
- `enhanced_module_02_exam_101_200.csv`
- `enhanced_module_03_exam_201_300.csv`
- `enhanced_module_04_exam_301_400.csv`
- `enhanced_module_05_exam_401_500.csv`
- `enhanced_module_06_exam_501_600.csv`

`main.py` is included too, but for deployment choose `streamlit_app.py`.

## Fast deploy steps
1. Create a new GitHub repository.
2. Upload all files from this folder to the root of the repo.
3. Go to Streamlit Community Cloud and sign in with GitHub.
4. Click **Create app**.
5. Choose your repository and branch.
6. Set the main file path to `streamlit_app.py`.
7. Click **Deploy**.
8. Open the generated `*.streamlit.app` link on your iPhone.

## Notes
- The app will automatically prefer the enhanced CSV files.
- On Community Cloud, local file storage is not guaranteed to persist forever. This means history / saved session files may reset at some point.
- The core exam engine will still run normally.

## Optional later upgrade
If you want permanent history and analytics online, move the attempt history from local CSV files to a cloud backend such as Google Sheets, Supabase, or SQLite on persistent storage.
