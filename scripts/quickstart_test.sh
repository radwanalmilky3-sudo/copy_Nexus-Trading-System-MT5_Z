#!/bin/bash
# quickstart_test.sh — دليل اختبار سريع لنظام Nexus Trader
# يوضح خطوات إدخال البيانات التاريخية وتشغيل النظام

set -e

echo "=================================================="
echo " Nexus Trader — دليل الاختبار السريع"
echo "=================================================="
echo ""
echo "الخطوة 1: التحقق من متغيرات البيئة"
echo "-------------------------------------"
grep -E "^(MT5_LOGIN|MT5_SERVER|MT5_PASSWORD|NEXUS_LLM_PROVIDER|NEXUS_LLM_MODEL|ZAI_API_KEY)=" .env
echo ""

echo "الخطوة 2: تشغيل نظام nexus-data فقط (للاختبار)"
echo "-----------------------------------------------"
echo "في نافذة منفذة: python run.py --services nexus-data,nexus-features,nexus-api"
echo ""

echo "الخطوة 3: جلب التاريخ من MT5"
echo "------------------------------"
echo "python scripts/import_historical_data.py --source mt5 --symbol XAUUSD --timeframe H1 --days 90"
echo ""

echo "الخطوة 4: التحقق من البيانات"
echo "-------------------------------"
echo "curl http://localhost:9001/ohlcv/XAUUSD/H1/provenance"
echo ""

echo "الخطوة 5: اختبار الـ API"
echo "-------------------------"
echo "curl http://localhost:9000/health"
echo ""
