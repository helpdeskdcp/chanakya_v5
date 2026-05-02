#!/bin/bash
echo "🔄 Restarting Chanakya AI v5..."
systemctl restart chanakya-v5.service
sleep 3
systemctl status chanakya-v5.service --no-pager | tail -5
curl -s http://localhost:5002/health
