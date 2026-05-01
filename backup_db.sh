#!/bin/bash
cd ~/bot_smm
source venv/bin/activate
railway run --service bot_smm pg_dump $DATABASE_URL > backups/backup_$(date +%Y%m%d_%H%M%S).sql
echo "Backup concluído: backups/backup_$(date +%Y%m%d_%H%M%S).sql"
