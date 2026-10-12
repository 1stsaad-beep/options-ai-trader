"""Compile and run the Android monitor's actual Java policy with the installed JDK."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='oat-monitor-policy-') as target:
    subprocess.run(['javac', '-d', target,
        str(root / 'android/app/src/main/java/com/optionsaitrader/options_ai_trader/MonitorPolicy.java'),
        str(root / 'test/native/MonitorPolicyTest.java')], check=True)
    subprocess.run(['java', '-cp', target, 'MonitorPolicyTest'], check=True)
