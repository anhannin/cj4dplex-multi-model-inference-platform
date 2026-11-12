"""Capture before traffic, outside kubelet rotation retention. Audit UUID coverage."""
from pathlib import Path
import subprocess


class LiveLogs:
    def __init__(self, root, label, models, start, popen=subprocess.Popen):
        self.root, self.label, self.models, self.start_time = Path(root), label, models, start
        self.popen = popen
        self.children = []

    def start(self):
        try:
            for model in self.models:
                stdout = (self.root / f'{self.label}-{model}.log').open('x')
                try:
                    stderr = (self.root / f'{self.label}-{model}-capture-stderr.log').open('x')
                except Exception:
                    stdout.close()
                    raise
                try:
                    process = self.popen(['kubectl', '-n', 'cj-inference', 'logs', 'deployment/' + model, '--follow=true', '--timestamps=true', '--since-time=' + self.start_time], stdout=stdout, stderr=stderr, text=True)
                except Exception:
                    stdout.close()
                    stderr.close()
                    raise
                self.children.append((process, stdout, stderr))
        except Exception:
            self.close()
            raise

    def close(self):
        for process, stdout, stderr in self.children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            stdout.close()
            stderr.close()
        self.children.clear()
