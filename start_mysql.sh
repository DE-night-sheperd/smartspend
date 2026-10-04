#!/bin/bash
PROJECT_DIR="/home/de_night_shepherd/Desktop/smartspend"
DATA_DIR="$PROJECT_DIR/mysql_data/data"
SOCKET="$PROJECT_DIR/mysql_data/mysql.sock"
PID_FILE="$PROJECT_DIR/mysql_data/mysql.pid"
PORT=3307

mkdir -p "$PROJECT_DIR/mysql_data"

echo "Starting MariaDB on port $PORT..."
/usr/sbin/mariadbd \
  --datadir="$DATA_DIR" \
  --socket="$SOCKET" \
  --pid-file="$PID_FILE" \
  --port=$PORT \
  --bind-address=127.0.0.1 \
  --user=$USER \
  2>&1 | tee "$PROJECT_DIR/mysql_data/error.log"
