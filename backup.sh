#!/data/data/com.termux/files/usr/bin/bash

cd ~/bot_smm

# Nome do backup com data
BACKUP="backup_$(date +%Y%m%d).tar.gz"

# Criar backup
tar -czf $BACKUP database/ logs/ *.py

# Apagar backups antigos (manter só o mais recente)
ls -t backup_*.tar.gz | tail -n +2 | xargs rm -f

echo "Backup criado: $BACKUP"
