from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as out:
    subprocess.run(['javac','-d',out,str(root/'android/app/src/main/java/com/optionsaitrader/options_ai_trader/AlpacaPolicy.java'),str(root/'test/native/AlpacaPolicyTest.java')],check=True)
    subprocess.run(['java','-cp',out,'AlpacaPolicyTest'],check=True)
