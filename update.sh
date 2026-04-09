#!/data/data/com.termux/files/usr/bin/bash

cd ~/bot_smm
source venv/bin/activate
pip install -r requirements.txt --upgrade
pkill -f "python main.py"
python main.py &
