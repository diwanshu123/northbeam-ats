# Setup guide

Time needed: about 10 minutes. You only need Python. No database, no cloud account, no money.

---

## Windows

**1. Install Python (once)**
- Go to https://www.python.org/downloads/ and download Python 3.10 or newer.
- Open the installer. **Tick the box "Add python.exe to PATH"**. Then click Install.

**2. Get the code**
- With Git: `git clone <the repository link>`
- Without Git: click the green **Code** button on GitHub, choose **Download ZIP**, then unzip it.

**3. Open a Command Prompt inside the project folder**
- Open the project folder in File Explorer.
- Click the address bar at the top, type `cmd`, and press Enter.

**4. Set everything up (once)**

```
setup.bat
```

Wait 2 to 4 minutes. At the end you must see **SETUP FINISHED**, and just before it the
five control totals, each with the word **TIES**.

**5. Start the app**

```
run.bat
```

**6. Open your browser** and go to http://127.0.0.1:8000

**7. Log in.** The password is the same for everyone: `Northbeam-Demo-2026`

| Who | Email | What you should see |
|---|---|---|
| Hiring manager | uday.varma@northbeam.example | 3 requisitions |
| Recruiter | rahul.singh@northbeam.example | 9 requisitions |
| Admin | simran.jain@northbeam.example | all 26 requisitions |

Click a requisition row to see its candidates. Log out and log in as another person to see
that each person sees only their own requisitions.

**8. Stop the app:** go to the Command Prompt window and press `Ctrl+C`.

---

## Mac or Linux

```
git clone <the repository link>
cd <the project folder>
bash setup.sh
bash run.sh
```

Then open http://127.0.0.1:8000 and log in with the same emails and password as above.

---

## Check that everything is correct

Open a Command Prompt (Terminal) in the project folder and activate the private Python folder first:

| | Windows | Mac / Linux |
|---|---|---|
| Activate | `.venv\Scripts\activate` | `source .venv/bin/activate` |

Then:

```
python -m src.reconciliation
pytest -q
```

- `python -m src.reconciliation` prints five lines. Each line must end with `TIES`.
- `pytest -q` must end with `48 passed`.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| `Python was not found` | Install Python (step 1). Tick "Add python.exe to PATH". Open a **new** window. |
| `ModuleNotFoundError: No module named 'duckdb'` | You are not in the private Python folder. Activate it (see the table above), or run `setup.bat` again. |
| `Please run setup.bat first` | Run `setup.bat` once. It makes the data and the logins. |
| Browser says "can't connect" | `run.bat` is not running. Start it and keep that window open. |
| `Wrong email or password` | Use the exact emails above and the password `Northbeam-Demo-2026`. |
| `Too many failed attempts` | Wait 5 minutes, or stop the app (`Ctrl+C`) and start it again. |
| `Address already in use` | Another copy is running. Close it, or restart your computer. |
| PowerShell blocks activation | Use Command Prompt (`cmd`) instead of PowerShell. |

---

## The same steps by hand (if the scripts do not work)

Windows:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m src.pipeline.bronze
python -m src.pipeline.silver
python -m src.pipeline.gold
python -m src.reconciliation
set DEMO_PASSWORD=Northbeam-Demo-2026
python -m src.api.seed_auth
set JWT_SECRET=type-any-long-random-text-of-at-least-32-characters
uvicorn src.api.main:app
```

Mac or Linux: the same, but use `source .venv/bin/activate` to activate, and `export` instead of `set`.

---

## Notes

- The demo password is only for local use. The app is **not deployed** anywhere. The README explains
  what I would change before real users touched it.
- To use different passwords, set `DEMO_PASSWORD` before running setup. If you do not set it, the setup
  scripts use the demo password above.
- Everything the pipeline makes (`warehouse.duckdb`, `auth.duckdb`) is rebuilt by `setup`. You can
  delete both files and run setup again at any time.
