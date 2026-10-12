# Windows PowerShell setup

```powershell
# 1. Unzip dealerdesk.zip, then:
cd path\to\dealerdesk
py -3.11 -m venv .venv          # any Python 3.11+ works
.\.venv\Scripts\Activate.ps1    # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt

# 2. Config
Copy-Item .env.example .env
notepad .env                    # set DATABASE_URL (Neon string) and GEMINI_API_KEY

# 3. Database + data
python manage.py makemigrations --check    # expect: No changes detected
python manage.py migrate --noinput
python manage.py seed_data
python manage.py seed_data                 # second run must add nothing

# 4. Tests that need no key
python -m unittest discover -s tests -t .
python manage.py test

# 5. Run + smoke test (second terminal for the mock and the smoke test)
python manage.py runserver 0.0.0.0:8000 --noreload
python supplier_mock\mock_supplier.py
python smoke_test.py --base-url http://localhost:8000 --track aiml
python smoke_test.py --base-url http://localhost:8000 --all
```

# Push to GitHub
```powershell
git init
git add .
git status                                  # confirm .env is NOT listed
git commit -m "DealerDesk: AI/ML track (assistant, forecast, order engine, supplier sync, portal)"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```
Create the empty public repo on github.com first (no README/licence). Add the video link to README.md and commit again.
