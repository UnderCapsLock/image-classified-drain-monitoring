#!/bin/bash
# DrainWatch — start everything and open launcher

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║     DrainWatch Starting Up       ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# Kill anything already on these ports
fuser -k 5000/tcp 2>/dev/null
fuser -k 5001/tcp 2>/dev/null
sleep 0.5

# Start servers
python3 server.py &
PID1=$!
python3 mock_server.py &
PID2=$!

echo "  ✓ Live server  → http://localhost:5000"
echo "  ✓ Mock server  → http://localhost:5001"
echo ""
echo "  Opening launcher in browser..."
sleep 1.5

# Open launcher in default browser (Linux Mint)
xdg-open "$(pwd)/launcher.html"

echo ""
echo "  Press Ctrl+C to stop both servers."
echo ""

trap "echo ''; echo '  Stopping servers...'; kill $PID1 $PID2 2>/dev/null; exit" INT
wait
