"""Streamlit entry point for the bindsight web app.

Any Streamlit runtime can serve this repository by running this file; it
only imports and calls :func:`bindsight.report.webapp.main`. The hosted
instance is the Hugging Face Space at
https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight, which builds from
``main`` on every release.

To run locally:

    pip install -e ".[report]"
    bindsight ui          # or: streamlit run streamlit_app.py
"""

from bindsight.report.webapp import main

if __name__ == "__main__":
    main()
