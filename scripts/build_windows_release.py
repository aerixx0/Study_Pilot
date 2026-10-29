"""Build a Windows source ZIP from a committed Git revision, never local data."""
import argparse
import io
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


def build(ref, output):
    root=Path(__file__).resolve().parents[1]
    archive=subprocess.check_output(['git','archive','--format=zip','--prefix=StudyPilot-Windows/',ref],cwd=root)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as target:
        for info in source.infolist():
            path=PurePosixPath(info.filename)
            if path.is_absolute() or '..' in path.parts or any(p in path.parts for p in ['data','.git','.venv','.runtime','verification','__pycache__']):
                raise ValueError('Unexpected private/runtime path in source archive.')
            if path.name.startswith('.env') and path.name!='.env.example':
                raise ValueError('Environment credentials must not be packaged.')
            data=source.read(info)
            if path.suffix.lower()=='.cmd':
                data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            target.writestr(info.filename,data)
        target.writestr('StudyPilot-Windows/START-HERE.txt',
            'STUDYPILOT - WINDOWS ONLY\r\n\r\n'
            'Website (no installation): https://study-pilot-olive.vercel.app/\r\n\r\n'
            'Local Windows app:\r\n'
            '1. Install Python 3.12 or later from https://www.python.org/downloads/windows/\r\n'
            '2. Extract the entire ZIP, then open StudyPilot-Windows.\r\n'
            '3. Double-click Start-StudyPilot.cmd. Keep its window open.\r\n'
            '4. Initial setup downloads dependencies; the browser opens when ready.\r\n'
            'Local address: http://127.0.0.1:8501/\r\n\r\n'
            'This source package needs Python; it is not a standalone EXE installer.\r\n'
            'The local Streamlit interface is Chinese. The website supports English and Chinese.\r\n'
            'Local and website accounts are separate. Read Usage.md for details.\r\n'
            'No macOS or Linux local package is provided at this stage.\r\n')
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive integrity check failed.')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref',default='HEAD')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(build(args.ref,args.output))
