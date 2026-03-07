#!/bin/bash

# Inicia o background worker no background
python3 worker.py > /tmp/worker.log 2>&1 &

# Inicia o Streamlit
streamlit run app.py --server.port=8080 --server.address=0.0.0.0 --server.maxUploadSize=10
