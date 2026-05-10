"""Streamlit Cloud entry point — deploys this repo as a public web app.

Streamlit Cloud (https://share.streamlit.io) auto-discovers ``streamlit_app.py``
at the repo root. Pointing it at this file is enough; everything else is in the
``bindsight`` package.

To deploy:

1. Push this repo to GitHub.
2. Go to https://share.streamlit.io → New app → pick this repo + main branch.
3. Streamlit Cloud installs from ``requirements.txt`` and runs this file.
4. Public URL: ``https://<app-name>.streamlit.app``

To run locally instead:

    pip install -e ".[report]"
    bindsight ui          # or: streamlit run streamlit_app.py
"""

from bindsight.report.webapp import main

if __name__ == "__main__":
    main()
