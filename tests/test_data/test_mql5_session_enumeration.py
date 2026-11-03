"""Run the actual Sessions function as C++ with only terminal APIs substituted.

This tests enumeration logic, not the live MQL5 runtime or broker connectivity.
"""
import os
from pathlib import Path
import subprocess

import pytest


def test_session_enumeration_distinguishes_end_from_failure(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows MSVC harness')
    locator = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if not locator.exists():
        pytest.skip('MSVC locator unavailable')
    installation = subprocess.check_output([str(locator), '-latest', '-products', '*', '-property', 'installationPath'], text=True).strip()
    setup = Path(installation) / 'VC/Auxiliary/Build/vcvars64.bat'
    if not installation or not setup.exists():
        pytest.skip('MSVC C++ tools unavailable')
    source = (Path(__file__).resolve().parents[2] / 'mql5/Indicators/NexusSessionReader.mq5').read_text(encoding='utf-8')
    function = source.split('string Sessions(', 1)[1].split('\nvoid ExportSessions()', 1)[0]
    harness = r'''
#include <string>
#include <cstdio>
#include <cstdarg>
using string=std::string;
using uint=unsigned int;
using datetime=long long;
using ENUM_DAY_OF_WEEK=int;
const int SYMBOL_SELECT=1, TERMINAL_CONNECTED=2, ERR_MARKET_SESSION_INDEX=4307;
int available=0, terminal_error=0, last_error=0;
bool synchronized=false;
void ResetLastError(){last_error=0;}
int GetLastError(){return last_error;}
bool SymbolInfoInteger(string,int,long &selected){selected=1;return true;}
bool TerminalInfoInteger(int){return true;}
bool SymbolIsSynchronized(string){return synchronized;}
bool SymbolInfoSessionQuote(string,int,uint index,datetime &from,datetime &to){
  if(index >= (uint)available){last_error=terminal_error;return false;}
  from=3600+index*60;to=3660+index*60;return true;
}
bool SymbolInfoSessionTrade(string s,int d,uint i,datetime &f,datetime &t){return SymbolInfoSessionQuote(s,d,i,f,t);}
string StringFormat(const char *fmt,...){char b[256];va_list a;va_start(a,fmt);vsnprintf(b,sizeof(b),fmt,a);va_end(a);return b;}
'''
    harness += 'string Sessions(' + function
    harness += r'''
int main(){
  for(bool quote : {true,false}){
    for(int count : {0,1,2}){
      for(int end_error : {0,4307,4302,4304}){
        available=count;terminal_error=end_error;string state;int error=-1;
        string windows=Sessions("XAUUSD",1,quote,state,error);
        bool normal=end_error==0 || end_error==4307;
        string expected=normal ? (count ? "ok" : "no_sessions") : "error";
        int expected_error=normal ? 0 : end_error;
        if(state!=expected || error!=expected_error){
          fprintf(stderr,"quote=%d count=%d terminal=%d: state=%s error=%d expected=%s/%d\n",quote,count,end_error,state.c_str(),error,expected.c_str(),expected_error);return 1;
        }
        if(count==0 && windows!="[]") return 2;
        if(count>0 && windows.find("3600")==string::npos) return 3;
      }
    }
    available=33;terminal_error=4307;string state;int error;
    Sessions("XAUUSD",1,quote,state,error);
    if(state!="truncated") return 4;
  }
}
'''
    (tmp_path / 'enumeration.cpp').write_text(harness, encoding='utf-8')
    build = subprocess.run(f'cmd.exe /d /s /c ""{setup}" >nul && cl /nologo /EHsc /std:c++17 enumeration.cpp /Fe:enumeration.exe"', cwd=tmp_path, capture_output=True, text=True, timeout=360)
    assert build.returncode == 0, build.stdout + build.stderr
    result = subprocess.run([str(tmp_path / 'enumeration.exe')], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
