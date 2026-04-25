#!/usr/bin/env python3
"""IPTV Player — PyQt6. Wymagania: pip install PyQt6 requests"""
import sys,os,json,re,base64
from pathlib import Path
from urllib.parse import quote_plus

from PyQt6.QtWidgets import (
    QScrollArea, QGridLayout, QCheckBox,
    QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QPushButton,QSlider,QLabel,QLineEdit,QSizePolicy,QSplitter,
    QListWidget,QListWidgetItem,QComboBox,QDialog,QFormLayout,
    QDialogButtonBox,QStatusBar,QFrame,QProgressBar,QMessageBox,
    QMenu,QFileDialog,QAbstractItemView
)
from PyQt6.QtMultimedia import QMediaPlayer,QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt,QUrl,QTimer,QThread,pyqtSignal,QSize
from PyQt6.QtGui import QKeyEvent,QDragEnterEvent,QDropEvent,QColor,QAction,QPixmap,QIcon
from PyQt6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply

APP_DIR=Path(os.environ.get("APPDATA",Path.home()))/"iptv-player"
SETTINGS_F=APP_DIR/"settings.json"
LANG_F=APP_DIR/"lang_cache.json"
FAV_F=APP_DIR/"favorites.json"
APP_DIR.mkdir(parents=True,exist_ok=True)
REC_DIR=Path(os.path.expanduser('~'))/'Videos'/'IPTV_Recordings'
REC_DIR.mkdir(parents=True,exist_ok=True)
REC_F=APP_DIR/'recordings.json'
SCHED_F=APP_DIR/'schedule.json'  # planned recordings
HIST_F=APP_DIR/'history.json'

def _check_pin(parent,cfg):
    """Ask for PIN. Returns True if correct or no PIN set."""
    pin=cfg.get('parental_pin','')
    if not pin:return True
    dlg=QDialog(parent)
    dlg.setWindowTitle('Kontrola rodzicielska')
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setStyleSheet(QSS)
    l=QVBoxLayout(dlg)
    l.addWidget(QLabel('Podaj PIN aby uzyskać dostęp:'))
    pe=QLineEdit();pe.setMaxLength(4);pe.setEchoMode(QLineEdit.EchoMode.Password)
    pe.setPlaceholderText('••••');pe.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pe.setFixedHeight(36);pe.setStyleSheet('font-size:20px;letter-spacing:4px;')
    l.addWidget(pe)
    err=QLabel('');err.setStyleSheet('color:#c41e3a;font-size:11px;');l.addWidget(err)
    bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept);bb.rejected.connect(dlg.reject);l.addWidget(bb)
    pe.returnPressed.connect(dlg.accept)
    # Auto-check on 4 digits
    def on_text(t):
        if len(t)==4:
            if t==pin:dlg.accept()
            else:err.setText('Błędny PIN');pe.clear()
    pe.textChanged.connect(on_text)
    if dlg.exec()!=QDialog.DialogCode.Accepted:return False
    return pe.text()==pin

def _is_adult_cat(cat_name):
    """Check if category name suggests adult content."""
    n=str(cat_name).lower()
    return any(kw in n for kw in('adult','xxx','erotic','18+','18 ','porno','sex '))

def _save_hist(e):
    try:
        h=load_json(HIST_F) or []
        h=[x for x in h if x.get('sid')!=e.get('sid')]
        h.insert(0,e);save_json(HIST_F,h[:500])
    except:pass

def _get_hist(sid):
    try:
        for x in(load_json(HIST_F) or []):
            if x.get('sid')==sid:return x
    except:pass
    return None

def load_json(p):
    try:
        f=Path(p)
        if f.exists():return json.loads(f.read_text("utf-8"))
    except:pass
    return {}

def save_json(p,d):
    try:Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2),"utf-8")
    except:pass

def http_get(url,timeout=30):
    import requests
    r=requests.get(url,timeout=timeout,verify=False,
                   headers={"User-Agent":"VLC/3.0 LibVLC/3.0.18","Accept":"*/*"},
                   allow_redirects=True)
    r.raise_for_status()
    return r.text

def xc_base(c):
    return f"{c['server'].rstrip('/')}/player_api.php?username={quote_plus(c['user'])}&password={quote_plus(c['pass'])}"

def b64d(s):
    try:return base64.b64decode(s).decode("utf-8",errors="replace")
    except:return str(s)

def fmt_t(ms):
    s=ms//1000;h,r=divmod(s,3600);m,sc=divmod(r,60)
    return f"{h}:{m:02d}:{sc:02d}" if h else f"{m}:{sc:02d}"

PL_RE=re.compile(r'\bPL\b|\bPOL\b|POLSKA|LEKTOR|DUBBING|NAPISY',re.I)

class FnThread(QThread):
    done=pyqtSignal(object);err=pyqtSignal(str)
    def __init__(self,fn):super().__init__();self._fn=fn
    def run(self):
        try:self.done.emit(self._fn())
        except Exception as e:self.err.emit(str(e))

QSS="""
*{font-family:'Segoe UI',sans-serif;}
QMainWindow,QWidget{background:#0d0d0f;color:#e4e4ef;}
QSplitter::handle{background:#1a1a20;width:2px;height:2px;}
QListWidget{background:#0f0f14;border:none;outline:none;font-size:13px;color:#dcdcf0;}
QListWidget::item{padding:6px 10px;border-bottom:1px solid #1a1a24;min-height:38px;}
QListWidget::item:hover{background:#1e1e2e;color:#fff;}
QListWidget::item:selected{background:#2a2a5a;color:#fff;border-left:3px solid #7c6af7;}
QLineEdit{background:#1a1a22;border:1px solid #2a2a38;color:#e4e4ef;padding:4px 8px;border-radius:5px;font-size:12px;}
QLineEdit:focus{border-color:#7c6af7;}
QPushButton{background:#1e1e2a;border:1px solid #2a2a38;color:#c0c0d4;padding:4px 12px;border-radius:5px;font-size:12px;}
QPushButton:hover{background:#2a2a3a;color:#fff;}
QPushButton:pressed{background:#333348;}
QPushButton:checked{background:#252550;color:#7c6af7;border-color:#4a4a8a;}
QComboBox{background:#1a1a22;border:1px solid #2a2a38;color:#c0c0d4;padding:3px 6px;border-radius:5px;font-size:11px;}
QComboBox QAbstractItemView{background:#1a1a22;border:1px solid #3a3a50;color:#c0c0d4;}
QComboBox::drop-down{border:none;width:16px;}
QSlider::groove:horizontal{background:#2a2a38;height:4px;border-radius:2px;}
QSlider::sub-page:horizontal{background:#7c6af7;height:4px;border-radius:2px;}
QSlider::handle:horizontal{background:#fff;width:13px;height:13px;margin:-5px 0;border-radius:7px;}
QProgressBar{background:#1a1a22;border:none;height:2px;border-radius:1px;}
QProgressBar::chunk{background:#7c6af7;}
QStatusBar{background:#09090c;color:#555;font-size:10px;}
QMenu{background:#1a1a22;border:1px solid #2a2a38;color:#c0c0d4;}
QMenu::item:selected{background:#2a2a42;}
QScrollBar:vertical{background:#0d0d0f;width:5px;}
QScrollBar::handle:vertical{background:#2a2a38;border-radius:2px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
"""

class SeekBar(QSlider):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setRange(0,1000)
    def mousePressEvent(self,e):
        if e.button()==Qt.MouseButton.LeftButton:
            v=int(e.position().x()/max(1,self.width())*self.maximum())
            self.setValue(v);self.sliderMoved.emit(v)
        super().mousePressEvent(e)

class OSD(QWidget):
    def __init__(self,parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setVisible(False)
        self._t=QTimer(self);self._t.setSingleShot(True);self._t.timeout.connect(self.hide)
        l=QVBoxLayout(self);l.setContentsMargins(0,0,0,0);l.addStretch()
        bar=QWidget();bar.setStyleSheet("background:rgba(0,0,0,160);")
        bl=QVBoxLayout(bar);bl.setContentsMargins(16,8,16,8);bl.setSpacing(2)
        self.n=QLabel("");self.n.setStyleSheet("color:#fff;font-size:15px;font-weight:bold;")
        self.e=QLabel("");self.e.setStyleSheet("color:#aaa;font-size:11px;")
        bl.addWidget(self.n);bl.addWidget(self.e);l.addWidget(bar)
    def show_info(self,name,epg="",secs=4):
        self.n.setText(name);self.e.setText(epg)
        self.setVisible(True);self._t.start(secs*1000)
    def resizeEvent(self,e):self.setGeometry(self.parent().rect());super().resizeEvent(e)

class ConnDlg(QDialog):
    def __init__(self,s,parent=None):
        super().__init__(parent);self.setWindowTitle("Połącz z XC Codes")
        self.setMinimumWidth(360);self.setStyleSheet(QSS)
        l=QVBoxLayout(self);f=QFormLayout()
        self.url=QLineEdit(s.get("server",""));self.url.setPlaceholderText("http://server:8080")
        self.usr=QLineEdit(s.get("user",""))
        self.pwd=QLineEdit(s.get("pass",""));self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        f.addRow("URL:",self.url);f.addRow("Login:",self.usr);f.addRow("Hasło:",self.pwd)
        l.addLayout(f)
        self.err_lbl=QLabel("");self.err_lbl.setStyleSheet("color:#e05252;font-size:11px;")
        l.addWidget(self.err_lbl)
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Połącz")
        bb.accepted.connect(self.accept);bb.rejected.connect(self.reject);l.addWidget(bb)
    def creds(self):
        return {"server":self.url.text().strip().rstrip("/"),
                "user":self.usr.text().strip(),"pass":self.pwd.text().strip()}

class SettingsDlg(QDialog):
    def __init__(self,s,parent=None):
        super().__init__(parent);self.setWindowTitle('Ustawienia')
        self.setMinimumWidth(380);self.setStyleSheet(QSS)
        l=QVBoxLayout(self);f=QFormLayout()
        self.omdb=QLineEdit(s.get('omdb_key',''));self.omdb.setPlaceholderText('Bezplatny klucz: omdbapi.com')
        self.buf=QComboBox();[self.buf.addItem(v) for v in['5s','10s','20s','30s','60s']]
        self.buf.setCurrentText(s.get('buffer','10s'))
        f.addRow('OMDB API Key:',self.omdb);f.addRow('Bufor live:',self.buf)
        l.addLayout(f)
        sep=QLabel('─── Historia oglądania ───');sep.setStyleSheet('color:#444;font-size:10px;')
        l.addWidget(sep)
        bh=QPushButton('Pokaż historię (ostatnie 20)');bh.setFixedHeight(26)
        bc=QPushButton('Wyczyść historię');bc.setFixedHeight(26)
        l.addWidget(bh);l.addWidget(bc)
        bh.clicked.connect(self._show_hist)
        bc.clicked.connect(lambda:(save_json(HIST_F,[]),bc.setText('Wyczyszczono!')))
        # Parental control section
        sep2=QLabel('─── Kontrola rodzicielska ───');sep2.setStyleSheet('color:#444;font-size:10px;')
        l.addWidget(sep2)
        self.pc_en=QCheckBox('Włącz kontrolę rodzicielską');self.pc_en.setChecked(bool(s.get('parental_pin','')))
        l.addWidget(self.pc_en)
        pin_row=QHBoxLayout()
        pin_row.addWidget(QLabel('PIN (4 cyfry):'))
        self.pc_pin=QLineEdit(s.get('parental_pin',''));self.pc_pin.setMaxLength(4)
        self.pc_pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pc_pin.setFixedWidth(80);self.pc_pin.setPlaceholderText('••••')
        pin_row.addWidget(self.pc_pin);pin_row.addStretch()
        l.addLayout(pin_row)
        pc_info=QLabel('Blokuje kategorie oznaczone jako 18+ lub zawierające: adult, xxx, erotic')
        pc_info.setStyleSheet('color:#555;font-size:10px;');pc_info.setWordWrap(True)
        l.addWidget(pc_info)
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept);bb.rejected.connect(self.reject);l.addWidget(bb)
    def _show_hist(self):
        h=load_json(HIST_F) or []
        if not h:QMessageBox.information(self,'Historia','Brak historii');return
        dlg=QDialog(self);dlg.setWindowTitle('Historia');dlg.resize(560,420);dlg.setStyleSheet(QSS)
        l=QVBoxLayout(dlg)
        lst=QListWidget()
        for x in h[:50]:
            import datetime
            try:dt=datetime.datetime.fromtimestamp(float(x.get('ts',0))).strftime('%d.%m %H:%M')
            except:dt='?'
            pos=x.get('pos',0);dur=x.get('dur',0)
            if dur>0:prog=f" [{pos//60000}:{pos%60000//1000:02d}/{dur//60000}:{dur%60000//1000:02d}]"
            else:prog=''
            it=QListWidgetItem(f"{dt}  {x.get('name','')}{prog}")
            it.setData(Qt.ItemDataRole.UserRole,x);lst.addItem(it)
        l.addWidget(lst,1)
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject);l.addWidget(bb)
        dlg.exec()
    def vals(self):
        v={'omdb_key':self.omdb.text().strip(),'buffer':self.buf.currentText()}
        if self.pc_en.isChecked() and len(self.pc_pin.text())==4:
            v['parental_pin']=self.pc_pin.text()
        else:
            v['parental_pin']=''
        return v

class EpsDlg(QDialog):
    play_sig=pyqtSignal(str,str)
    def __init__(self,series,data,creds,parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Odcinki — {series.get('name','')}")
        self.resize(720,540)
        if parent:self.setStyleSheet(parent.styleSheet())
        self._c=creds;self._s=series
        l=QVBoxLayout(self);l.setContentsMargins(10,10,10,10);l.setSpacing(6)
        info=data.get("info",{}) or {}
        if info.get("plot"):
            p=QLabel(info["plot"][:200]);p.setStyleSheet("color:#888;font-size:10px;")
            p.setWordWrap(True);l.addWidget(p)
        from PyQt6.QtWidgets import QTabWidget
        tabs=QTabWidget()
        tabs.setStyleSheet("QTabBar::tab{padding:4px 16px;font-size:11px;}QTabBar::tab:selected{color:#c41e3a;border-bottom:2px solid #c41e3a;}")
        episodes=data.get("episodes",{})
        if not episodes:
            tabs.addTab(QLabel("Brak odcinkow."),"–")
        else:
            for season in sorted(episodes.keys(),key=lambda x:(int(x) if str(x).isdigit() else 999)):
                ew=QListWidget()
                ew.setStyleSheet("QListWidget{background:#0a0a12;border:none;font-size:12px;}"
                    "QListWidget::item{padding:8px 12px;border-bottom:1px solid #1a1a22;}"
                    "QListWidget::item:selected{background:#1e1e3a;color:#fff;border-left:3px solid #c41e3a;}"
                    "QListWidget::item:hover{background:#151520;}")
                series_sid=str(series.get('series_id','') or series.get('stream_id',''))
                prog=parent._series_progress.get(series_sid,{}) if parent else {}
                last_num=str(prog.get('ep_num',''))
                for ep in episodes[season]:
                    num=ep.get("episode_num","")
                    title=ep.get("title") or f"Odcinek {num}"
                    dur=ep.get("duration_secs","") or ep.get("duration","")
                    try:dur_s=f"  {int(float(dur))//60}min" if dur else ""
                    except:dur_s=""
                    prefix='▶ ' if str(num)==last_num else ''
                    it=QListWidgetItem(f"{prefix}E{str(num).zfill(2)}  {title}{dur_s}" if num else title)
                    it.setData(Qt.ItemDataRole.UserRole,ep)
                    if str(num)==last_num:
                        it.setForeground(QColor('#c41e3a'))
                    ew.addItem(it)
                ew.itemDoubleClicked.connect(self._play_ep)
                tabs.addTab(ew,f"Sezon {season}")
        l.addWidget(tabs,1)
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject);l.addWidget(bb)
    def _play_ep(self,it):
        ep=it.data(Qt.ItemDataRole.UserRole)
        c=self._c;eid=ep.get("id","");ext=ep.get("container_extension","mkv")
        if not c or not eid:return
        url=f"{c['server'].rstrip('/')}/series/{c['user']}/{c['pass']}/{eid}.{ext}"
        num=ep.get("episode_num","");title=ep.get("title","")
        full=f"{self._s.get('name','')} E{num} — {title}".strip(" —")
        # Pass episode list to player for auto-next
        if self.parent():
            # Flatten all episodes in current season
            try:
                tab=self.tabs if hasattr(self,'tabs') else None
                ep_list=[]
                for i in range(ep_widget.count() if (ep_widget:=tab.currentWidget() if tab else None) else 0):
                    it3=ep_widget.item(i)
                    if it3:ep_list.append(it3.data(Qt.ItemDataRole.UserRole))
                self.parent()._cur_ep_list=ep_list
                self.parent()._cur_ep_idx=ep_list.index(ep) if ep in ep_list else 0
                self.parent()._cur_series_name=self._s.get('name','')
                self.parent()._cur_ep_season=str(getattr(self,'_cur_season','1'))
            except:pass
        self.play_sig.emit(url,full);self.accept()

class IPTVPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPTV Player")
        self.resize(1400,860);self.setMinimumSize(900,580)
        self.setAcceptDrops(True);self.setStyleSheet(QSS)
        self._cfg=load_json(SETTINGS_F)
        self._langs=load_json(LANG_F)
        self._favs={t:set(load_json(FAV_F).get(t,[])) for t in("live","vod","series")}
        self._creds=self._cfg.get("creds")
        self._cats={"live":[],"vod":[],"series":[]}
        self._streams=[];self._tab="live";self._cat_id=None
        self._epg={};self._fs=False;self._seeking=False
        self._filtered=[];self._render_offset=0
        self._cur_ch=None;self._cur_idx=-1
        self._threads=[];self._scan_abort=False
        self._nam=QNetworkAccessManager()
        self._logo_cache={};self._logo_pending={}
        self._scan_probe=None
        self._series_langs=load_json(APP_DIR/'series_lang.json')
        self._hidden_cats=load_json(APP_DIR/'hidden_cats.json')
        self._osc_timer=QTimer(self);self._osc_timer.setSingleShot(True)
        self._osc_ref=None;self._cur_trailer='';self._resume_pos=0;self._cur_url=None
        self._cur_ep_list=None;self._cur_ep_idx=None;self._cur_series_name='';self._cur_ep_season='1'
        self._rec_proc=None;self._rec_file=None;self._rec_start=None
        self._thumb_cache={};self._thumb_in_progress=set()
        self._series_progress=load_json(APP_DIR/'series_progress.json') or {}
        self._sched_timer=QTimer(self);self._sched_timer.timeout.connect(self._check_schedule)
        self._sched_timer.start(15000)  # check every 15s
        self._active_recs={}  # sid+start -> proc
        # Clean stale active flags on startup
        QTimer.singleShot(1000,self._clean_stale_schedule)
        self._epg_timer=QTimer(self);self._epg_timer.timeout.connect(self._refresh_epg)
        self._build()
        self._sigs()
        self._osc_timer.timeout.connect(lambda:self._osc_ref.hide() if self._fs and self._osc_ref else None)
        self._epg_timer.start(60000)  # refresh EPG every 60s
        self.setMouseTracking(True)
        if self._creds:QTimer.singleShot(400,self._load_cats)

    def _build(self):
        root=QWidget();self.setCentralWidget(root)
        rl=QVBoxLayout(root);rl.setContentsMargins(0,0,0,0);rl.setSpacing(0)

        # topbar
        tb=QWidget();tb.setStyleSheet("background:#0a0a0e;border-bottom:1px solid #1a1a28;")
        tb.setFixedHeight(44);tbl=QHBoxLayout(tb);tbl.setContentsMargins(10,6,10,6);tbl.setSpacing(6)
        self.b_live=QPushButton("📡 Live");self.b_vod=QPushButton("🎬 Filmy");self.b_ser=QPushButton("📺 Seriale")
        self.b_lib=QPushButton("Nagrania");self.b_lib.setFixedHeight(26)
        self.b_guide=QPushButton("Przewodnik");self.b_guide.setFixedHeight(26)
        self.b_catchup=QPushButton("Archiwum");self.b_catchup.setFixedHeight(26)
        for b in(self.b_live,self.b_vod,self.b_ser):b.setFixedHeight(28);tbl.addWidget(b)
        tbl.addWidget(self.b_guide);tbl.addWidget(self.b_catchup);tbl.addWidget(self.b_lib)
        tbl.addSpacing(8)
        self.srch=QLineEdit();self.srch.setPlaceholderText("Szukaj…");self.srch.setFixedHeight(28);self.srch.setMaximumWidth(220)
        tbl.addWidget(self.srch)
        self.f_pl=QPushButton("PL");self.f_pla=QPushButton("Audio PL");self.f_pls=QPushButton("Napisy PL");self.f_fav=QPushButton("Ulubione")
        self.f_genre=QComboBox();self.f_genre.addItem("Gatunek...");self.f_genre.setFixedWidth(110);self.f_genre.setFixedHeight(26)
        for b in(self.f_pl,self.f_pla,self.f_pls,self.f_fav):b.setFixedHeight(26);b.setCheckable(True);tbl.addWidget(b)
        tbl.addWidget(self.f_genre);tbl.addStretch()
        self.b_conn=QPushButton("🔌 Połącz");self.b_sett=QPushButton("⚙️")
        self.b_conn.setFixedHeight(28);self.b_sett.setFixedHeight(28);self.b_sett.setFixedWidth(32)
        self.b_conn.setStyleSheet("background:#7c6af7;color:#fff;border-color:#7c6af7;")
        tbl.addWidget(self.b_conn);tbl.addWidget(self.b_sett)
        rl.addWidget(tb)
        self.prog=QProgressBar();self.prog.setFixedHeight(2);self.prog.setRange(0,0);self.prog.hide()
        rl.addWidget(self.prog)

        # scan bar
        sbar=QWidget();sbar.setStyleSheet("background:#0a0a18;border-bottom:1px solid #2a2a50;")
        sbar.setFixedHeight(28);sbl=QHBoxLayout(sbar);sbl.setContentsMargins(10,3,10,3)
        self.scan_lbl=QLabel("Skanowanie…");self.scan_lbl.setStyleSheet("color:#7cb8d4;font-size:11px;")
        self.scan_prg=QProgressBar();self.scan_prg.setFixedHeight(4);self.scan_prg.setRange(0,100)
        self.scan_stop=QPushButton("Stop");self.scan_stop.setFixedSize(50,20)
        sbl.addWidget(self.scan_lbl,1);sbl.addWidget(self.scan_prg,2);sbl.addWidget(self.scan_stop)
        self.sbar=sbar;self.sbar.hide();rl.addWidget(self.sbar)

        # main split
        self.msplit=QSplitter(Qt.Orientation.Horizontal);rl.addWidget(self.msplit,1)

        # sidebar
        sb=QWidget();sb.setStyleSheet("background:#0a0a0e;border-right:1px solid #1a1a28;")
        sb.setMinimumWidth(160);sb.setMaximumWidth(230)
        sbl2=QVBoxLayout(sb);sbl2.setContentsMargins(0,0,0,0);sbl2.setSpacing(0)
        hdr=QLabel("KATEGORIE");hdr.setStyleSheet("color:#444;font-size:9px;letter-spacing:1px;padding:5px 10px;")
        sbl2.addWidget(hdr)
        self.cat_srch=QLineEdit();self.cat_srch.setPlaceholderText('Szukaj kat...');self.cat_srch.setFixedHeight(24)
        sbl2.addWidget(self.cat_srch)
        self.cat_list=QListWidget();sbl2.addWidget(self.cat_list,1)
        self.b_manage=QPushButton('Ukryj kategorie');self.b_manage.setFixedHeight(22)
        self.b_manage.setStyleSheet('font-size:10px;color:#444;border-color:#1a1a1a;')
        sbl2.addWidget(self.b_manage);self.msplit.addWidget(sb)

        # center
        cw=QWidget();cwl=QVBoxLayout(cw);cwl.setContentsMargins(0,0,0,0);cwl.setSpacing(0)
        self.vsplit=QSplitter(Qt.Orientation.Vertical)

        # player widget
        pw=QWidget();pw.setStyleSheet("background:#000;")
        pwl=QVBoxLayout(pw);pwl.setContentsMargins(0,0,0,0);pwl.setSpacing(0)
        self.vcon=QWidget();self.vcon.setStyleSheet("background:#000;")
        vcl=QVBoxLayout(self.vcon);vcl.setContentsMargins(0,0,0,0)
        self.video=QVideoWidget();self.video.setStyleSheet("background:#000;")
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.player=QMediaPlayer();self.aout=QAudioOutput()
        self.player.setAudioOutput(self.aout);self.player.setVideoOutput(self.video)
        self.aout.setVolume(1.0);vcl.addWidget(self.video)
        self.osd=OSD(self.vcon);pwl.addWidget(self.vcon,1)

        # OSC
        osc=QWidget();osc.setStyleSheet("background:#0d0d12;border-top:1px solid #1a1a28;");osc.setFixedHeight(70)
        ol=QVBoxLayout(osc);ol.setContentsMargins(10,4,10,6);ol.setSpacing(3)
        self.seek=SeekBar();ol.addWidget(self.seek)
        cr=QHBoxLayout();cr.setSpacing(2)
        def mkb(t,tip="",w=32):b=QPushButton(t);b.setToolTip(tip);b.setFixedSize(w,26);return b
        self.b_prev=mkb("⏮","Poprzedni kanał [P]");self.b_back=mkb("⏪","Cofnij 10s [←]")
        self.b_play=mkb("⏯","Play/Pause [Spacja]");self.b_fwd=mkb("⏩","Przewiń 10s [→]")
        self.b_next=mkb("⏭","Następny kanał [N]");self.b_stop=mkb("⏹","Stop")
        self.tlbl=QLabel("0:00 / 0:00");self.tlbl.setStyleSheet("color:#777;font-size:11px;font-family:monospace;min-width:110px;")
        self.vol=QSlider(Qt.Orientation.Horizontal);self.vol.setRange(0,100);self.vol.setValue(100);self.vol.setFixedWidth(80)
        self.spd=QComboBox()
        [self.spd.addItem(s) for s in["0.25×","0.5×","0.75×","1×","1.25×","1.5×","2×","3×"]]
        self.spd.setCurrentIndex(3);self._speeds=[0.25,0.5,0.75,1.0,1.25,1.5,2.0,3.0]
        self.b_open=mkb("📂","Otwórz plik",34);self.b_fs=mkb("⛶","Pełny ekran (F)",34)
        self.b_scan=mkb("🔍","Skanuj języki")
        self.audio_lbl=QLabel("🎙")
        self.audio_lbl.setStyleSheet("color:#555;font-size:12px;")
        self.audio_sel=QComboBox()
        self.audio_sel.setFixedWidth(90)
        self.audio_sel.setToolTip("Ścieżka audio")
        self.audio_sel.hide()
        self.sub_lbl=QLabel('Sub');self.sub_lbl.setStyleSheet('color:#555;font-size:10px;');self.sub_lbl.hide()
        self.sub_sel=QComboBox();self.sub_sel.setFixedWidth(85);self.sub_sel.hide()
        self.b_tracks=QPushButton('Jezyki');self.b_tracks.setFixedHeight(24)
        self.b_rec=QPushButton('⏺');self.b_rec.setFixedHeight(24);self.b_rec.setFixedWidth(28)
        self.b_rec.setToolTip('Nagrywaj / Zatrzymaj nagrywanie')
        self.b_rec.setStyleSheet('color:#ff4444;font-size:14px;background:#1a0000;border-color:#440000;')
        self.b_rec.setCheckable(True)
        for w in[self.b_prev,self.b_back,self.b_play,self.b_fwd,self.b_next,self.b_stop,
                 self.tlbl,self.vol,self.spd,self.audio_lbl,self.audio_sel,self.sub_lbl,self.sub_sel]:cr.addWidget(w)
        cr.addStretch();cr.addWidget(self.b_rec);cr.addWidget(self.b_tracks);cr.addWidget(self.b_scan);cr.addWidget(self.b_open);cr.addWidget(self.b_fs)
        ol.addLayout(cr);pwl.addWidget(osc)

        # EPG info bar (live TV)
        self.epg_bar=QWidget()
        self.epg_bar.setStyleSheet("background:#08080f;border-top:1px solid #1a1a28;")
        self.epg_bar.setFixedHeight(48)
        ebl=QVBoxLayout(self.epg_bar);ebl.setContentsMargins(12,4,12,4);ebl.setSpacing(2)
        self.epg_now_w=QLabel("▶ TERAZ")
        self.epg_now_w.setStyleSheet("color:#7c6af7;font-size:10px;font-weight:bold;")
        self.epg_title_w=QLabel("")
        self.epg_title_w.setStyleSheet("color:#e4e4ef;font-size:12px;font-weight:bold;")
        self.epg_desc_w=QLabel('')  # shown on hover
        self.epg_next_w=QLabel('')
        self.epg_next_w.setStyleSheet("color:#555;font-size:10px;")
        ebl.addWidget(self.epg_now_w)
        # Title + next in one row
        epg_row=QHBoxLayout();epg_row.setSpacing(16)
        epg_row.addWidget(self.epg_title_w,2)
        epg_row.addWidget(self.epg_next_w,1)
        ebl.addLayout(epg_row)
        self.epg_bar.hide()
        # Expand EPG bar on hover to show description
        self.epg_bar._collapsed_h=48
        self.epg_bar._expanded_h=120
        def _epg_enter(e):
            desc=self.epg_desc_w.text()
            if desc:
                self.epg_bar.setFixedHeight(self.epg_bar._expanded_h)
                self.epg_desc_w.show()
        def _epg_leave(e):
            self.epg_bar.setFixedHeight(self.epg_bar._collapsed_h)
            self.epg_desc_w.hide()
        self.epg_bar.enterEvent=_epg_enter
        self.epg_bar.leaveEvent=_epg_leave
        self.epg_desc_w.setWordWrap(True)
        self.epg_desc_w.setStyleSheet('color:#aaaabc;font-size:11px;padding:0 4px;')
        self.epg_desc_w.hide()  # hidden by default, shown on hover
        ebl.addWidget(self.epg_desc_w)
        pwl.addWidget(self.epg_bar)

        # EPG floating overlay (fullscreen hover tooltip)
        self.epg_overlay=QWidget(self.vcon)
        self.epg_overlay.setStyleSheet(
            'background:rgba(0,0,0,200);border-radius:10px;')
        self.epg_overlay.hide()
        ov_l=QVBoxLayout(self.epg_overlay);ov_l.setContentsMargins(14,10,14,10);ov_l.setSpacing(4)
        self.epg_ov_ch=QLabel('')
        self.epg_ov_ch.setStyleSheet('color:#aaa;font-size:11px;')
        self.epg_ov_now=QLabel('')
        self.epg_ov_now.setStyleSheet('color:#fff;font-size:15px;font-weight:bold;')
        self.epg_ov_time=QLabel('')
        self.epg_ov_time.setStyleSheet('color:#c41e3a;font-size:11px;')
        self.epg_ov_next=QLabel('')
        self.epg_ov_next.setStyleSheet('color:#888;font-size:12px;')
        self.epg_ov_desc=QLabel('')
        self.epg_ov_desc.setStyleSheet('color:#bbb;font-size:11px;')
        self.epg_ov_desc.setWordWrap(True)
        for w in[self.epg_ov_ch,self.epg_ov_now,self.epg_ov_time,self.epg_ov_next,self.epg_ov_desc]:
            ov_l.addWidget(w)
        self._epg_overlay_timer=QTimer(self);self._epg_overlay_timer.setSingleShot(True)
        self._epg_overlay_timer.timeout.connect(self.epg_overlay.hide)

        self.vsplit.addWidget(pw)

        # channel list
        chw=QWidget();chw.setStyleSheet("background:#0d0d11;border-top:1px solid #1a1a28;")
        cwl2=QVBoxLayout(chw);cwl2.setContentsMargins(0,0,0,0);cwl2.setSpacing(0)
        chdr=QWidget();chdr.setStyleSheet("background:#0a0a0e;");chdr.setFixedHeight(26)
        chdrl=QHBoxLayout(chdr);chdrl.setContentsMargins(10,3,10,3)
        self.cnt=QLabel('—');self.cnt.setStyleSheet('color:#444;font-size:10px;')
        self.sortb=QComboBox();[self.sortb.addItem(s) for s in['A-Z','Ocena','Rok']];self.sortb.setFixedWidth(80)
        self.b_gridview=QPushButton('⊞');self.b_gridview.setFixedSize(24,22)
        self.b_gridview.setCheckable(True);self.b_gridview.setToolTip('Widok siatki')
        self.b_gridview.setStyleSheet('font-size:14px;padding:0;')
        chdrl.addWidget(self.cnt);chdrl.addStretch();chdrl.addWidget(QLabel('Sort:'));chdrl.addWidget(self.sortb);chdrl.addWidget(self.b_gridview)
        cwl2.addWidget(chdr)
        self.clist=QListWidget();self.clist.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # Grid view
        self.grid_w=QWidget();self.grid_w.setStyleSheet('background:#0a0a10;')
        self.grid_layout=QGridLayout(self.grid_w);self.grid_layout.setSpacing(10);self.grid_layout.setContentsMargins(10,10,10,10)
        self.grid_scroll=QScrollArea();self.grid_scroll.setWidget(self.grid_w)
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_scroll.hide()
        cwl2.addWidget(self.clist,1)
        cwl2.addWidget(self.grid_scroll,1)

        self.info_w=QWidget()
        self.info_w.setStyleSheet('background:#08080f;border-top:2px solid #1e1e30;')
        self.info_w.setMinimumHeight(110)
        _il=QHBoxLayout(self.info_w);_il.setContentsMargins(12,8,12,8);_il.setSpacing(12)
        self.info_cover=QLabel();self.info_cover.setFixedSize(70,98)
        self.info_cover.setStyleSheet('background:#111120;border-radius:4px;')
        self.info_cover.setAlignment(Qt.AlignmentFlag.AlignCenter);self.info_cover.hide()
        _il.addWidget(self.info_cover)
        _it=QWidget();_itl=QVBoxLayout(_it);_itl.setContentsMargins(0,0,0,0);_itl.setSpacing(3)
        _r1=QHBoxLayout();_r1.setSpacing(8)
        self.info_title=QLabel('');self.info_title.setStyleSheet('color:#f0f0ff;font-size:14px;font-weight:bold;')
        self.info_trailer=QPushButton('Trailer');self.info_trailer.setFixedHeight(20)
        self.info_trailer.setStyleSheet('background:#c41e3a;color:#fff;border:none;border-radius:3px;font-size:10px;padding:0 8px;')
        self.info_trailer.hide()
        self.info_imdb=QPushButton('IMDB ↗');self.info_imdb.setFixedHeight(20)
        self.info_imdb.setStyleSheet('background:#f5c518;color:#000;border:none;border-radius:3px;font-size:10px;padding:0 8px;')
        self.info_imdb.hide()
        _r1.addWidget(self.info_title);_r1.addWidget(self.info_trailer);_r1.addWidget(self.info_imdb);_r1.addStretch()
        _itl.addLayout(_r1)
        self.info_meta=QLabel('');self.info_meta.setStyleSheet('color:#7c6af7;font-size:11px;')
        _itl.addWidget(self.info_meta)
        self.info_plot=QLabel('');self.info_plot.setStyleSheet('color:#9090a8;font-size:11px;')
        self.info_plot.setWordWrap(True);self.info_plot.setAlignment(Qt.AlignmentFlag.AlignTop)
        _itl.addWidget(self.info_plot,1);_il.addWidget(_it,1)
        self.info_w.hide();cwl2.addWidget(self.info_w)
        self.info_w.mouseDoubleClickEvent=lambda e:self._on_info_dbl()
        self.vsplit.addWidget(chw)
        self.vsplit.setSizes([640,220]);cwl.addWidget(self.vsplit)
        self.msplit.addWidget(cw);self.msplit.setSizes([200,1200])

        self.sb2=QStatusBar();self.sb2.setFixedHeight(20);self.setStatusBar(self.sb2)
        self.sb2.showMessage("Brak połączenia")
        self._uitimer=QTimer();self._uitimer.timeout.connect(self._tick);self._uitimer.start(250)

    def _sigs(self):
        self.b_conn.clicked.connect(self._show_conn)
        self.b_sett.clicked.connect(self._show_sett)
        self.b_live.clicked.connect(lambda:self._tab_sw("live"))
        self.b_vod.clicked.connect(lambda:self._tab_sw("vod"))
        self.b_ser.clicked.connect(lambda:self._tab_sw("series"))
        self.srch.textChanged.connect(lambda:self._render())
        self.sortb.currentIndexChanged.connect(lambda:self._render())
        for b in(self.f_pl,self.f_pla,self.f_pls,self.f_fav):b.toggled.connect(lambda _:self._render())
        self.f_genre.currentTextChanged.connect(lambda _:self._render())
        self.cat_list.currentRowChanged.connect(self._on_cat)
        self.cat_srch.textChanged.connect(lambda q:[self.cat_list.item(i).setHidden(bool(q) and q.lower() not in self.cat_list.item(i).text().lower()) for i in range(self.cat_list.count())])
        self.b_manage.clicked.connect(self._manage_cats)
        self.b_gridview.toggled.connect(self._toggle_grid_view)
        self.clist.itemDoubleClicked.connect(self._on_dbl)
        self.clist.itemClicked.connect(self._on_click)
        self.clist.customContextMenuRequested.connect(self._ctx)
        self.b_play.clicked.connect(self._toggle_play)
        self.b_stop.clicked.connect(self.player.stop)
        self.b_prev.clicked.connect(self._prev)
        self.b_next.clicked.connect(self._next)
        self.b_back.clicked.connect(lambda:self.player.setPosition(max(0,self.player.position()-10000)))
        self.b_fwd.clicked.connect(lambda:self.player.setPosition(self.player.position()+10000))
        self.b_fs.clicked.connect(self._toggle_fs)
        self.b_open.clicked.connect(self._open)
        self.b_scan.clicked.connect(self._scan_start)
        self.scan_stop.clicked.connect(self._scan_abort_fn)
        self.vol.valueChanged.connect(lambda v:self.aout.setVolume(v/100))
        self.spd.currentIndexChanged.connect(lambda i:self.player.setPlaybackRate(self._speeds[i]))
        self.audio_sel.currentIndexChanged.connect(self._on_audio_track)
        self.sub_sel.currentIndexChanged.connect(lambda i:QTimer.singleShot(0,lambda ii=i:self._do_sub(ii-1)) if i>0 else None)
        self.b_tracks.clicked.connect(self._show_tracks)
        self.b_rec.toggled.connect(self._toggle_rec)
        self.b_lib.clicked.connect(self._show_library)
        self.b_guide.clicked.connect(self._show_guide)
        self.b_catchup.clicked.connect(self._check_catchup)
        self.info_trailer.clicked.connect(self._open_trailer)
        self.info_imdb.clicked.connect(self._open_imdb)
        self.seek.sliderPressed.connect(lambda:setattr(self,'_seeking',True))
        self.seek.sliderReleased.connect(self._seek_rel)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.player.playbackStateChanged.connect(lambda s:self.b_play.setText(
            "⏸" if s==QMediaPlayer.PlaybackState.PlayingState else "▶"))
        self.player.durationChanged.connect(lambda d:self.seek.setRange(0,max(1,d)))
        self.player.errorOccurred.connect(lambda _,s:self.sb2.showMessage(f"Błąd: {s}"))

    # ── Connection ─────────────────────────────────────────────────────────────
    def _show_conn(self):
        d=ConnDlg(self._cfg,self)
        if d.exec()!=QDialog.DialogCode.Accepted:return
        c=d.creds()
        if not c["server"] or not c["user"]:return
        self._creds=c;self._cfg["creds"]=c;save_json(SETTINGS_F,self._cfg);self._load_cats()

    def _show_sett(self):
        # Require PIN to open settings if parental control active
        if self._cfg.get('parental_pin'):
            if not _check_pin(self,self._cfg):
                self.sb2.showMessage('Błędny PIN');return
        d=SettingsDlg(self._cfg,self)
        if d.exec()==QDialog.DialogCode.Accepted:
            self._cfg.update(d.vals());save_json(SETTINGS_F,self._cfg)

    def _load_cats(self):
        if not self._creds:return
        self.prog.show();self.sb2.showMessage("Łączenie…")
        c=self._creds
        def fetch():
            b=xc_base(c);raw=http_get(b)
            if raw.strip().startswith("<"):raise RuntimeError("Serwer zwrócił HTML — sprawdź URL")
            auth=json.loads(raw)
            if(auth.get("user_info")or{}).get("auth")==0:raise RuntimeError("Błąd autoryzacji")
            return{"live":json.loads(http_get(b+"&action=get_live_categories")),
                   "vod":json.loads(http_get(b+"&action=get_vod_categories")),
                   "series":json.loads(http_get(b+"&action=get_series_categories"))}
        t=FnThread(fetch);t.done.connect(self._cats_ok);t.err.connect(self._cats_err);self._keep(t);t.start()

    def _cats_ok(self,d):
        self.prog.hide();self._cats=d
        self.sb2.showMessage(f"Polaczono Live:{len(d['live'])} Filmy:{len(d['vod'])} Seriale:{len(d['series'])}")
        self._tab_sw(self._tab)
        if self._favs.get("live"):
            for i in range(self.cat_list.count()):
                it=self.cat_list.item(i)
                if it and it.data(Qt.ItemDataRole.UserRole)=="__favs__":
                    self.cat_list.setCurrentRow(i);break

    def _cats_err(self,msg):
        self.prog.hide();self.sb2.showMessage(f"Błąd: {msg}")
        QMessageBox.critical(self,"Błąd połączenia",msg)

    def _tab_sw(self,tab):
        self._tab=tab
        acc="background:#252550;color:#7c6af7;border:1px solid #4a4a8a;"
        self.b_live.setStyleSheet(acc if tab=="live" else "")
        self.b_vod.setStyleSheet(acc if tab=="vod" else "")
        self.b_ser.setStyleSheet(acc if tab=="series" else "")
        self.b_scan.setVisible(tab!="live")
        self.f_pla.setVisible(tab!="live");self.f_pls.setVisible(tab!="live")
        if tab=="live":
            self.f_pla.setChecked(False);self.f_pls.setChecked(False)
            self.info_w.hide()
            # Show EPG category filter for live
            self._refresh_live_epg_filter()
        else:
            # vod/series: genre filter from stream metadata
            self.f_genre.blockSignals(True);self.f_genre.clear();self.f_genre.addItem("Gatunek...");self.f_genre.blockSignals(False)
            self.f_genre.setVisible(True)
        self._pop_cats()
        # For vod/series: don't auto-load 'Wszystkie' (too slow)
        # For live: auto-load (or favs if available)
        if self.cat_list.count():
            if tab=='live':
                # Try to select favs first
                favs_row=0
                for i in range(self.cat_list.count()):
                    it=self.cat_list.item(i)
                    if it and it.data(Qt.ItemDataRole.UserRole)=='__favs__' and self._favs.get('live'):
                        favs_row=i;break
                self.cat_list.setCurrentRow(favs_row)
            else:
                # vod/series: select first real category (not __all__)
                for i in range(self.cat_list.count()):
                    it=self.cat_list.item(i)
                    if it and it.data(Qt.ItemDataRole.UserRole) not in('__all__','__favs__',None):
                        self.cat_list.setCurrentRow(i);break
                else:
                    self.cat_list.setCurrentRow(0)

    def _pop_cats(self):
        self.cat_list.clear()
        for label,uid in[("📋 Wszystkie","__all__"),("❤️ Ulubione","__favs__")]:
            it=QListWidgetItem(label);it.setData(Qt.ItemDataRole.UserRole,uid);self.cat_list.addItem(it)
        _hid=set(self._hidden_cats.get(self._tab,[]))
        parental=bool(self._cfg.get('parental_pin',''))
        for c in self._cats.get(self._tab,[]):
            cid=str(c.get('category_id',''))
            if cid in _hid:continue
            cname=c.get('category_name','')
            # Block adult categories when parental control enabled
            if parental and _is_adult_cat(cname):continue
            it=QListWidgetItem(cname)
            it.setData(Qt.ItemDataRole.UserRole,cid)
            self.cat_list.addItem(it)

    def _on_cat(self,row):
        it=self.cat_list.item(row)
        if not it:return
        uid=it.data(Qt.ItemDataRole.UserRole)
        if not uid:return
        self._cat_id=uid
        if uid=="__favs__":self._load_streams("__all__")
        else:self._load_streams(uid)

    def _load_streams(self,cat_id):
        if not self._creds:return
        self.prog.show();self.clist.clear();self.cnt.setText('Ładowanie…')
        c=self._creds;tab=self._tab
        act={'live':'get_live_streams','vod':'get_vod_streams','series':'get_series'}[tab]
        hidden=set(self._hidden_cats.get(tab,[]))
        def fetch():
            if cat_id and cat_id not in('__all__','__favs__'):
                # Single category - direct API call
                url=xc_base(c)+f'&action={act}&category_id={cat_id}'
                return json.loads(http_get(url))
            else:
                # Load only from VISIBLE (non-hidden) categories
                cats=[cc for cc in (self._cats.get(tab,[]) or [])
                      if str(cc.get('category_id','')) not in hidden]
                if not cats:
                    url=xc_base(c)+f'&action={act}'
                    return json.loads(http_get(url))
                merged=[]
                for cc in cats:
                    try:
                        cid=cc.get('category_id','')
                        url=xc_base(c)+f'&action={act}&category_id={cid}'
                        merged+=json.loads(http_get(url))
                    except:pass
                return merged
        t=FnThread(fetch)
        t.done.connect(lambda d:self._streams_ok(d,tab))
        t.err.connect(lambda e:(self.prog.hide(),self.cnt.setText(f'Błąd: {e}')))
        self._keep(t);t.start()

    def _streams_ok(self,data,tab):
        self.prog.hide();self._streams=data
        try:
            genres=set()
            for ch in data:
                g=self._langs.get(str(ch.get('stream_id') or ch.get('series_id',''))or'',{}).get('genre','') or ch.get('genre','')
                if g:
                    for gg in str(g).split(','):genres.add(gg.strip())
            self.f_genre.blockSignals(True);self.f_genre.clear();self.f_genre.addItem('Gatunek...')
            for g in sorted(genres):self.f_genre.addItem(g)
            self.f_genre.blockSignals(False)
        except:pass
        self._render()
        # For live tab: fetch EPG for all channels in background
        if tab=='live':
            QTimer.singleShot(500,lambda:self._fetch_epg_batch_list(data[:200]))

    def _render(self,append=False):
        if append:
            self._render_page(self._render_offset)
            return
        q=self.srch.text().lower()
        fpl=self.f_pl.isChecked()
        fpa=self.f_pla.isChecked() and self._tab in("vod","series")
        fps=self.f_pls.isChecked() and self._tab in("vod","series")
        ffv=self.f_fav.isChecked() or self._cat_id=="__favs__"
        si=self.sortb.currentIndex();favs=self._favs[self._tab]
        src_data=self._streams
        if self._cat_id=="__favs__":
            src_data=[s for s in self._streams if str(s.get("stream_id") or s.get("series_id","")) in favs]
        res=[]
        for ch in src_data:
            name=ch.get("name","")
            sid=str(ch.get("stream_id") or ch.get("series_id",""))
            meta=(self._series_langs if self._tab=='series' else self._langs).get(sid)
            if q and q not in name.lower():continue
            if ffv and sid not in favs:continue
            if fpl and not(PL_RE.search(name)or(meta and(meta.get("plAudio")or meta.get("plSubs")))):continue
            if fpa and not(meta and meta.get("plAudio")):continue
            if fps and not(meta and meta.get("plSubs")):continue
            fg=self.f_genre.currentText()
            if fg and fg!='Gatunek...':
                if self._tab=='live':
                    # Filter by EPG program type (keyword-based)
                    # Filter by XC category group (reliable)
                    group_cats=getattr(self,'_live_group_cats',{})
                    cat_ids=group_cats.get(fg)
                    if cat_ids is not None:
                        ch_cat=str(ch.get('category_id',''))
                        if ch_cat not in cat_ids:continue
                else:
                    gs=(meta or {}).get('genre','') or ch.get('genre','') or ''
                    if fg.lower() not in gs.lower():continue
            res.append(ch)
        if si==0:res.sort(key=lambda x:x.get("name","").lower())
        elif si==1:
            def _rt(x):
                try:return float(str(x.get("rating") or 0).replace(",","."))
                except:return 0.0
            res.sort(key=_rt,reverse=True)
        elif si==2:
            def _yr(x):
                sid=str(x.get("stream_id") or x.get("series_id",""))
                y=self._langs.get(sid,{}).get("year","") or self._series_langs.get(sid,{}).get("year","")
                return str(y or x.get("year","") or x.get("releaseDate","") or "0")[:4]
            res.sort(key=_yr,reverse=True)
        self._filtered=res
        self._render_offset=0
        self.clist.clear()
        self._logo_pending.clear()
        self.cnt.setText(f'{len(res):,} wyników')
        self._render_page(0)
        # Refresh grid if visible
        if getattr(self,'b_gridview',None) and self.b_gridview.isChecked():
            self._render_grid()

    PAGE=200

    def _render_page(self,offset):
        favs=self._favs[self._tab]
        batch=self._filtered[offset:offset+self.PAGE]
        for i,ch in enumerate(batch):
            idx=offset+i
            sid=str(ch.get("stream_id") or ch.get("series_id",""))
            meta=self._langs.get(sid);isFav=sid in favs
            it=QListWidgetItem();it.setData(Qt.ItemDataRole.UserRole,ch)
            it.setData(Qt.ItemDataRole.UserRole+1,idx);it.setSizeHint(QSize(0,40))
            badge=""
            if meta:
                aL=meta.get("audio",[]); sL=meta.get("subs",[])
                # Build audio badge: PL first if present, then rest, no limit
                if aL:
                    PL=any(l in("pol","pl","polish","plk") for l in aL)
                    langs=[a.upper() for a in aL]
                    if PL:
                        # Move PL to front
                        pl_langs=[l for l in langs if l in("POL","PL","POLISH","PLK")]
                        other_langs=[l for l in langs if l not in("POL","PL","POLISH","PLK")]
                        badge+=" ●"+",".join(pl_langs)  # filled dot = PL present
                        if other_langs:badge+="+"+",".join(other_langs)
                    else:
                        badge+=" ["+",".join(langs)+"]"
                if sL:
                    PL_s=any(l in("pol","pl","polish","plk") for l in sL)
                    slangs=[s.upper() for s in sL]
                    if PL_s:
                        badge+=" ○"  # empty circle = PL subs
                    else:
                        badge+=" ("+",".join(slangs)+")"
            elif PL_RE.search(ch.get("name","")):badge+=" [PL]"
            star="❤ " if isFav else ""
            rt=ch.get("rating") or ch.get("rating_5based")
            try:rtxt=f" ★{float(str(rt).replace(',','.')):.1f}" if rt else ""
            except:rtxt=""
            it.setText(f"{star}{ch.get('name','')}{badge}{rtxt}")
            if isFav:it.setForeground(QColor("#ff8888"))
            # Only load logos if list is small enough
            if len(self._filtered)<=500:
                logo=ch.get("stream_icon") or ch.get("cover","")
                if logo:
                    ic=self._logo_cache.get(logo)
                    if ic:it.setIcon(ic)
                    else:self._load_logo(logo,it)
            self.clist.addItem(it)
        self._render_offset=offset+len(batch)
        # Add "load more" item if needed
        if self._render_offset < len(self._filtered):
            more=QListWidgetItem(f"... Załaduj więcej ({self._render_offset:,} / {len(self._filtered):,})")
            more.setData(Qt.ItemDataRole.UserRole,"__more__")
            more.setForeground(QColor("#7c6af7"))
            more.setSizeHint(QSize(0,36))
            self.clist.addItem(more)


    def _on_click(self,it):
        ch=it.data(Qt.ItemDataRole.UserRole)
        if not ch or ch=="__more__":return
        self._cur_ch=ch;self._cur_idx=it.data(Qt.ItemDataRole.UserRole+1)
        name_ch=ch.get("name","")
        if self._tab=='live':
            self.info_cover.setPixmap(QPixmap());self.info_cover.hide()
            self.info_trailer.hide();self._cur_trailer=''
            sid=str(ch.get('stream_id',''))
            logo=ch.get('stream_icon','')
            if logo:self._load_img(logo,self.info_cover,52,52)
            epg=self._epg.get(sid)
            if epg:
                self.osd.show_info(name_ch,epg.get('title',''))
                self._show_epg_bar(epg)
                self.info_title.setText(epg.get('title',name_ch))
                self.info_meta.setText(name_ch)
                self.info_plot.setText(epg.get('desc','')[:300])
            else:
                self._fetch_epg(sid,name_ch)
                self.info_title.setText(name_ch)
                self.info_meta.setText('Pobieranie EPG...')
                self.info_plot.setText('')
            self.info_w.show()
        elif self._tab in("vod","series"):
            self.epg_bar.hide()
            self.info_title.setText(name_ch)
            self.info_meta.setText("Pobieranie info…")
            self.info_plot.setText("")
            self.info_w.show()
            self._fetch_movie(ch)

    def _on_dbl(self,it):
        ch=it.data(Qt.ItemDataRole.UserRole)
        if ch=="__more__":
            # Remove "load more" item and render next page
            self.clist.takeItem(self.clist.count()-1)
            self._render_page(self._render_offset)
            return
        if not ch:return
        self._cur_ch=ch;self._cur_idx=it.data(Qt.ItemDataRole.UserRole+1)
        if self._tab=='series':self._open_series(ch);return
        url=self._url(ch)
        if url:self._play(url,ch.get('name',''))

    def _url(self,ch):
        if not self._creds:return None
        c=self._creds;sid=ch.get("stream_id") or ch.get("series_id","")
        sv=c['server'].rstrip('/')
        if self._tab=="live":return f"{sv}/live/{c['user']}/{c['pass']}/{sid}.ts"
        elif self._tab=="vod":
            ext=ch.get("container_extension") or "mp4"
            return f"{sv}/movie/{c['user']}/{c['pass']}/{sid}.{ext}"
        return None

    def _ctx(self,pos):
        it=self.clist.itemAt(pos)
        if not it:return
        ch=it.data(Qt.ItemDataRole.UserRole)
        if ch=="__more__":return
        sid=str(ch.get("stream_id") or ch.get("series_id",""))
        fav=sid in self._favs[self._tab]
        menu=QMenu(self)
        ap=menu.addAction("▶ Odtwórz")
        af=menu.addAction("💔 Usuń z ulubionych" if fav else "❤️ Dodaj do ulubionych")
        menu.addSeparator()
        asc=menu.addAction("🔍 Skanuj języki")
        act=menu.exec(self.clist.mapToGlobal(pos))
        if act==ap:self._on_dbl(it)
        elif act==af:
            if fav:self._favs[self._tab].discard(sid)
            else:self._favs[self._tab].add(sid)
            self._save_favs();self._render()
        elif act==asc:self._scan_one(ch)

    def _save_favs(self):save_json(FAV_F,{t:list(v) for t,v in self._favs.items()})

    def _prev(self):
        if hasattr(self,'b_gridview') and self.b_gridview.isChecked() and self._filtered:
            idx=getattr(self,'_cur_grid_idx',1)-1
            if idx>=0:
                self._cur_grid_idx=idx
                ch=self._filtered[idx]
                self._cur_ch=ch
                if self._tab=='live':
                    url=self._url(ch)
                    if url:self._play(url,ch.get('name',''))
            return
        prv=(self._cur_idx or 1)-1
        while prv>=0:
            it=self.clist.item(prv)
            d=it.data(Qt.ItemDataRole.UserRole) if it else None
            if d and d not in(None,'__more__'):
                self.clist.setCurrentRow(prv)
                self._on_click(it)
                if self._tab=='live':self._on_dbl(it)
                return
            prv-=1

    def _next(self):
        # Use clist if visible, else filtered list
        if hasattr(self,'b_gridview') and self.b_gridview.isChecked() and self._filtered:
            idx=getattr(self,'_cur_grid_idx',0)+1
            if idx<len(self._filtered):
                self._cur_grid_idx=idx
                ch=self._filtered[idx]
                self._cur_ch=ch
                if self._tab=='live':
                    url=self._url(ch)
                    if url:self._play(url,ch.get('name',''))
            return
        nxt=(self._cur_idx or 0)+1
        while nxt<self.clist.count():
            it=self.clist.item(nxt)
            d=it.data(Qt.ItemDataRole.UserRole) if it else None
            if d and d not in(None,'__more__'):
                self.clist.setCurrentRow(nxt)
                self._on_click(it)
                if self._tab=='live':self._on_dbl(it)
                return
            nxt+=1

    def _play(self,url,title=''):
        self.audio_sel.blockSignals(True);self.audio_sel.clear();self.audio_sel.hide();self.audio_lbl.hide();self.audio_sel.blockSignals(False)
        self.sub_sel.blockSignals(True);self.sub_sel.clear();self.sub_sel.hide();self.sub_lbl.hide();self.sub_sel.blockSignals(False)
        self._cur_url=url
        # Warn if this stream is being recorded (would cause conflict)
        rec_url=getattr(self,'_rec_file',None)
        if rec_url and self._rec_proc and self._rec_proc.poll() is None:
            # Check if it's same stream (matching URL)
            pass  # recording uses separate ffmpeg process - no conflict with Qt player
        # Warn if SCHEDULED recording is active for this channel
        sched=load_json(SCHED_F) or []
        active_sched=[r for r in sched if r.get('active') and r.get('url')==url]
        if active_sched:
            r2=active_sched[0]
            from PyQt6.QtWidgets import QMessageBox
            btn=QMessageBox.warning(self,'Nagrywanie w toku',
                f'Ten kanał jest aktualnie nagrywany przez planer:\n{r2.get("title","?")}\n\n'
                f'Odtwarzanie tego samego strumienia może zakłócić nagranie.\n'
                f'Zalecane: ogladaj na innym urządzeniu lub poczekaj do końca nagrania.',
                QMessageBox.StandardButton.Ok|QMessageBox.StandardButton.Cancel)
            if btn==QMessageBox.StandardButton.Cancel:return  # don't play
        self.player.setSource(QUrl(url));self.player.play()
        self.setWindowTitle(f'IPTV — {title}');self.sb2.showMessage(f'▶ {title}')
        if self._tab!='live':
            import time
            sid=str((self._cur_ch or {}).get('stream_id') or (self._cur_ch or {}).get('series_id',''))
            _save_hist({'sid':sid,'name':title,'tab':self._tab,'url':url,'pos':0,'dur':0,'ts':time.time()})
            h=_get_hist(sid)
            if h and h.get('pos',0)>30000 and h.get('dur',0)>0:
                m2=h['pos']//60000;s2=h['pos']%60000//1000
                self.sb2.showMessage(f'▶ {title}  [Ostatnio: {m2}:{s2:02d}] — R=wznow')
                self._resume_pos=h['pos']
            else:self._resume_pos=0
            QTimer.singleShot(2000,self._show_tracks)
        if self._cur_ch:
            sid=str(self._cur_ch.get("stream_id",""))
            epg=self._epg.get(sid)
            self.osd.show_info(title,epg.get("title","") if epg else "")

    def _toggle_play(self):
        if self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:self.player.pause()
        else:self.player.play()

    def _seek_rel(self):
        self._seeking=False;self.player.setPosition(self.seek.value())

    def _tick(self):
        pos=self.player.position();dur=self.player.duration()
        if not self._seeking and dur:
            self.seek.blockSignals(True);self.seek.setValue(pos);self.seek.blockSignals(False)
        self.tlbl.setText(f'{fmt_t(pos)} / {fmt_t(dur)}')
        if self._tab!='live' and self._cur_ch and dur and pos>0:
            lh=getattr(self,'_last_hist_pos',0)
            if pos-lh>10000:
                self._last_hist_pos=pos
                import time
                sid=str(self._cur_ch.get('stream_id') or self._cur_ch.get('series_id',''))
                _save_hist({'sid':sid,'name':self.windowTitle().replace('IPTV — ',''),
                           'tab':self._tab,'url':self._cur_url or '','pos':pos,'dur':dur,'ts':time.time()})

    def _toggle_fs(self):
        if not self._fs:
            self.showFullScreen();self._fs=True;self.b_fs.setText('[ ] Exit')
            self.msplit.widget(0).hide();self.vsplit.widget(1).hide()
            self.info_w.hide()
            for i in range(self.centralWidget().layout().count()-1):
                w=self.centralWidget().layout().itemAt(i).widget()
                if w:w.hide()
            pw=self.vsplit.widget(0)
            for i in range(pw.layout().count()):
                w=pw.layout().itemAt(i).widget()
                if w and w.height()==70:self._osc_ref=w;w.hide();break
            # Keep EPG bar visible in fullscreen if data available
            if self._tab=='live' and self._cur_ch:
                sid=str(self._cur_ch.get('stream_id',''))
                if self._epg.get(sid):self.epg_bar.show()
            self._osc_timer.start(3000)
        else:
            self.showNormal();self._fs=False;self.b_fs.setText('⛶')
            self.msplit.widget(0).show();self.vsplit.widget(1).show()
            for i in range(self.centralWidget().layout().count()-1):
                w=self.centralWidget().layout().itemAt(i).widget()
                if w:w.show()
            self.sbar.hide()
            if self._osc_ref:self._osc_ref.show()
            self._osc_timer.stop()

    def _show_epg_overlay(self):
        if not self._cur_ch:return
        sid=str(self._cur_ch.get('stream_id',''))
        epg=self._epg.get(sid)
        if not epg:return
        name=self._strip_ch_prefix(self._cur_ch.get('name',''))
        self.epg_ov_ch.setText(name)
        self.epg_ov_now.setText(epg.get('title','')[:60])
        # Time
        try:
            import datetime as _dt
            s=_dt.datetime.fromisoformat(epg['start'].replace(' ','T'))
            e=_dt.datetime.fromisoformat(epg['end'].replace(' ','T'))
            now=_dt.datetime.now()
            elapsed=max(0,int((now-s).total_seconds()))
            total=max(1,int((e-s).total_seconds()))
            pct=min(100,elapsed*100//total)
            self.epg_ov_time.setText(f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}  ({pct}%)")
        except:self.epg_ov_time.setText('')
        nxt=epg.get('next','')
        self.epg_ov_next.setText(f'Nastepnie: {nxt}' if nxt else '')
        self.epg_ov_desc.setText(epg.get('desc','')[:120])
        self.epg_overlay.adjustSize()
        # Position: top-right of video
        vw=self.vcon.width();vh=self.vcon.height()
        ow=min(380,vw-40);oh=self.epg_overlay.sizeHint().height()
        self.epg_overlay.setGeometry(vw-ow-20,20,ow,oh)
        self.epg_overlay.show();self.epg_overlay.raise_()
        self._epg_overlay_timer.start(4000)  # hide after 4s

    def _strip_ch_prefix(self,name):
        """Remove IPTV prefixes like 'PL VIP: ', 'PL HD: ' etc."""
        import re as _re
        # Remove patterns like 'PL HD: ', 'PL VIP: ', 'ENG: ', 'DE: ', '4K: ', etc.
        return _re.sub(r'^[A-Z0-9 ]{1,10}:\s+','',name).strip()

    def _fetch_epg(self,sid,name=""):
        if not self._creds:return
        c=self._creds
        def fetch():
            url=xc_base(c)+f"&action=get_short_epg&stream_id={sid}&limit=2"
            d=json.loads(http_get(url));lst=d.get("epg_listings",[])
            if not lst:return None
            cur=lst[0];nxt=lst[1] if len(lst)>1 else {}
            return{"title":b64d(cur.get("title","")),
                   "desc":b64d(cur.get("description","")),
                   "start":cur.get("start",""),"end":cur.get("end",""),
                   "next":b64d(nxt.get("title","")) if nxt else "",
                   "nextStart":nxt.get("start","") if nxt else "",
                   "genre":b64d(cur.get("genre","") or cur.get("category",""))}
        def on_done(epg):
            if epg:
                self._epg[sid]=epg
                if self._cur_ch and str(self._cur_ch.get('stream_id',''))==sid:
                    display_name=self._strip_ch_prefix(name)
                    self.osd.show_info(display_name,epg.get('title',''))
                    self._show_epg_bar(epg)
                    self.info_title.setText(epg.get('title',display_name))
                    self.info_meta.setText(display_name)
                    self.info_plot.setText(epg.get('desc','')[:300])
                    if self._tab=='live':self.epg_bar.show()
                # Update grid cell if visible
                if getattr(self,'b_gridview',None) and self.b_gridview.isChecked() and self._tab=='live':
                    self._update_grid_epg(sid,epg)
        t=FnThread(fetch);t.done.connect(on_done);self._keep(t);t.start()

    def _show_epg_bar(self,epg):
        if not epg:self.epg_bar.hide();return
        self.epg_title_w.setText(epg.get("title",""))
        nxt=epg.get("next","")
        nxt_s=epg.get("nextStart","")
        if nxt_s:
            try:
                import datetime
                dt=datetime.datetime.fromisoformat(nxt_s.replace(" ","T"))
                nxt_s=dt.strftime("%H:%M")+" "
            except:nxt_s=""
        self.epg_next_w.setText(f"→ {nxt_s}{nxt}" if nxt else "")
        self.epg_bar.setVisible(self._tab=="live")

    def _toggle_rec(self,on):
        if on:
            self._start_rec()
        else:
            self._stop_rec()

    def _start_rec(self):
        if not self._cur_url:
            self.sb2.showMessage('Brak aktywnego strumienia')
            self.b_rec.setChecked(False);return
        import subprocess as _sp,time as _t
        # Find ffmpeg
        ff=os.path.join(os.path.dirname(os.path.abspath(__file__)),'ffmpeg.exe')
        if not os.path.isfile(ff):
            import shutil;ff=shutil.which('ffmpeg') or shutil.which('ffmpeg.exe') or ''
        if not ff:
            QMessageBox.warning(self,'Brak ffmpeg','Wrzuc ffmpeg.exe do folderu playera')
            self.b_rec.setChecked(False);return
        # Build output filename
        name=self.windowTitle().replace('IPTV — ','').strip() or 'nagranie'
        name=re.sub(r'[<>:"/\\|?*]','_',name)
        ts=__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
        out=str(REC_DIR/f'{name}_{ts}.ts')
        try:
            self._rec_proc=_sp.Popen(
                [ff,'-i',self._cur_url,'-c','copy','-y',out],
                stdout=_sp.DEVNULL,stderr=_sp.DEVNULL
            )
            self._rec_file=out
            self._rec_start=_t.time()
            self.b_rec.setStyleSheet('color:#fff;font-size:14px;background:#c41e3a;border-color:#ff0000;')
            self.sb2.showMessage(f'⏺ Nagrywanie: {os.path.basename(out)}')
        except Exception as e:
            QMessageBox.warning(self,'Blad nagrywania',str(e))
            self.b_rec.setChecked(False)

    def _stop_rec(self):
        if self._rec_proc:
            try:self._rec_proc.terminate()
            except:pass
            self._rec_proc=None
            # Save to library
            if self._rec_file and os.path.isfile(self._rec_file):
                import time as _t
                recs=load_json(REC_F) or []
                dur=int(_t.time()-(self._rec_start or _t.time()))
                name=self.windowTitle().replace('IPTV — ','').strip()
                recs.insert(0,{'file':self._rec_file,'name':name,'dur':dur,'ts':_t.time()})
                save_json(REC_F,recs)
                sz=os.path.getsize(self._rec_file)//1024//1024
                self.sb2.showMessage(f'✔ Nagranie zapisane: {os.path.basename(self._rec_file)} ({sz} MB, {dur//60}:{dur%60:02d})')
            self._rec_file=None;self._rec_start=None
        self.b_rec.setStyleSheet('color:#ff4444;font-size:14px;background:#1a0000;border-color:#440000;')

    def _show_library(self):
        # Sync: scan folder for files not in JSON
        recs=load_json(REC_F) or []
        known={r.get('file') for r in recs}
        import glob,time as _t
        for f in sorted(glob.glob(str(REC_DIR/'*.ts'))+glob.glob(str(REC_DIR/'*.mp4'))+glob.glob(str(REC_DIR/'*.mkv')),key=os.path.getmtime,reverse=True):
            if f not in known:
                sz=os.path.getsize(f)
                recs.insert(0,{'file':f,'name':os.path.splitext(os.path.basename(f))[0],'dur':0,'ts':os.path.getmtime(f),'from_folder':True})
                known.add(f)
        # Remove entries for deleted files
        recs=[r for r in recs if os.path.isfile(r.get('file',''))]
        save_json(REC_F,recs)
        dlg=QDialog(self);dlg.setWindowTitle('📼 Biblioteka nagrań')
        dlg.resize(700,460);dlg.setStyleSheet(self.styleSheet())
        l=QVBoxLayout(dlg);l.setContentsMargins(10,10,10,10);l.setSpacing(6)
        # Header
        hdr=QHBoxLayout()
        hdr.addWidget(QLabel(f'Nagrania w: {REC_DIR}'))
        b_folder=QPushButton('Otwórz folder');b_folder.setFixedHeight(24)
        b_folder.clicked.connect(lambda:__import__('subprocess').Popen(['explorer',str(REC_DIR)]))
        hdr.addStretch();hdr.addWidget(b_folder)
        l.addLayout(hdr)
        lst=QListWidget()
        lst.setStyleSheet('QListWidget{background:#0a0a10;}QListWidget::item{padding:8px 12px;border-bottom:1px solid #1a1a22;}QListWidget::item:selected{background:#1e1e3a;color:#fff;border-left:3px solid #c41e3a;}')
        for r in recs:
            import datetime
            try:dt=datetime.datetime.fromtimestamp(float(r.get('ts',0))).strftime('%d.%m.%Y %H:%M')
            except:dt='?'
            dur=r.get('dur',0)
            fname=os.path.basename(r.get('file',''))
            sz=''
            try:sz=f'  {os.path.getsize(r["file"])//1024//1024} MB'
            except:pass
            it=QListWidgetItem(f"{dt}  {r.get('name','?')}  {dur//60}:{dur%60:02d}{sz}")
            it.setData(Qt.ItemDataRole.UserRole,r)
            lst.addItem(it)
        l.addWidget(lst,1)
        btns=QHBoxLayout()
        b_play=QPushButton('▶ Odtwórz');b_del=QPushButton('🗑 Usuń')
        b_play.setFixedHeight(26);b_del.setFixedHeight(26)
        btns.addWidget(b_play);btns.addWidget(b_del);btns.addStretch()
        l.addLayout(btns)
        def play_sel():
            it=lst.currentItem()
            if not it:return
            r=it.data(Qt.ItemDataRole.UserRole)
            f=r.get('file','')
            if f and os.path.isfile(f):
                self._play(QUrl.fromLocalFile(f).toString(),r.get('name','Nagranie'))
                # Show recording info in bottom panel
                self.info_title.setText(r.get('name','Nagranie'))
                dur=r.get('dur',0)
                import datetime as _dt
                try:dt=_dt.datetime.fromtimestamp(float(r.get('ts',0))).strftime('%d.%m.%Y %H:%M')
                except:dt='?'
                sz=''
                try:sz=f'  {os.path.getsize(f)//1024//1024} MB'
                except:pass
                self.info_meta.setText(f'Nagrano: {dt}  {dur//60}:{dur%60:02d}{sz}')
                self.info_plot.setText(f.replace(str(REC_DIR)+os.sep,''))
                self.info_cover.setPixmap(QPixmap());self.info_cover.hide()
                self.info_trailer.hide()
                self.info_w.show()
                self.epg_bar.hide()
                dlg.accept()
        def del_sel():
            it=lst.currentItem()
            if not it:return
            r=it.data(Qt.ItemDataRole.UserRole)
            f=r.get('file','')
            if QMessageBox.question(dlg,'Usunąć?',f'Usunąć {os.path.basename(f)}?')==QMessageBox.StandardButton.Yes:
                try:os.remove(f)
                except:pass
                recs2=[x for x in(load_json(REC_F) or []) if x.get('file')!=f]
                save_json(REC_F,recs2)
                lst.takeItem(lst.currentRow())
        b_play.clicked.connect(play_sel)
        b_del.clicked.connect(del_sel)
        lst.itemDoubleClicked.connect(lambda it:play_sel())
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject);l.addWidget(bb)
        dlg.exec()



    def _clean_stale_schedule(self):
        """On startup, mark past recordings as done."""
        import datetime as _dt
        now=_dt.datetime.now()
        sched=load_json(SCHED_F) or []
        changed=False
        for r in sched:
            try:
                end=_dt.datetime.fromisoformat(r['end'])
                if end<now and not r.get('done'):
                    r['done']=True;r['active']=False;changed=True
            except:pass
        if changed:save_json(SCHED_F,sched)


    def _check_catchup(self):
        if not self._creds:return
        c=self._creds
        self.sb2.showMessage('Sprawdzam catchup...')
        # Get visible category IDs (not hidden)
        hidden=set(self._hidden_cats.get('live',[]))
        visible_cats={str(cc.get('category_id','')) for cc in self._cats.get('live',[]) if str(cc.get('category_id','')) not in hidden}
        # Also include currently loaded streams if available
        loaded_sids={str(ch.get('stream_id','')) for ch in self._streams if isinstance(ch,dict)} if self._tab=='live' else set()
        def fetch():
            import json as _j
            try:
                url=xc_base(c)+'&action=get_live_streams'
                streams=_j.loads(http_get(url,timeout=8))
                # Filter: only catchup channels from visible categories
                chs=[s for s in streams
                     if (s.get('tv_archive',0) or s.get('catchup',0))
                     and (not visible_cats or str(s.get('category_id','')) in visible_cats
                          or str(s.get('stream_id','')) in loaded_sids)]
                return {'channels':chs,'count':len(chs),'total':sum(1 for s in streams if s.get('tv_archive',0) or s.get('catchup',0))}
            except Exception as e:
                return {'error':str(e)}
        def on_done(r):
            if r.get('error'):
                self.sb2.showMessage(f"Blad: {r['error']}");return
            chs=r.get('channels',[])
            count=r.get('count',0)
            total=r.get('total',0)
            if count==0:
                QMessageBox.information(self,'Catchup',
                    'Twoj serwer NIE obsluguje catchup.\nCatchup wymaga specjalnej licencji serwera XC.')
                self.sb2.showMessage('Serwer nie obsluguje catchup')
                return
            dlg=QDialog(self);dlg.setWindowTitle(f'Catchup — {count} kanalow')
            dlg.resize(600,480);dlg.setStyleSheet(self.styleSheet())
            l=QVBoxLayout(dlg);l.setContentsMargins(10,10,10,10);l.setSpacing(6)
            info_txt=f'Kanaly z archiwum w twoich kategoriach: {count}'
            if total>count:info_txt+=f' (ukryte: {total-count})'
            l.addWidget(QLabel(info_txt))
            lst=QListWidget()
            lst.setStyleSheet('QListWidget{background:#080810;}QListWidget::item{padding:7px 12px;border-bottom:1px solid #1a1a22;}QListWidget::item:selected{background:#1e1e3a;color:#fff;border-left:3px solid #c41e3a;}')
            for ch in chs:
                days=ch.get('tv_archive_duration',ch.get('catchup_days',0))
                it=QListWidgetItem(f"{ch.get('name','')}  [{days} dni wstecz]")
                it.setData(Qt.ItemDataRole.UserRole,ch)
                lst.addItem(it)
            l.addWidget(lst,1)
            btns=QHBoxLayout()
            b_play=QPushButton('Wybierz czas');b_play.setFixedHeight(26)
            btns.addWidget(b_play);btns.addStretch()
            l.addLayout(btns)
            b_play.clicked.connect(lambda:self._open_catchup_picker(lst.currentItem().data(Qt.ItemDataRole.UserRole),dlg) if lst.currentItem() else None)
            lst.itemDoubleClicked.connect(lambda it2:self._open_catchup_picker(it2.data(Qt.ItemDataRole.UserRole),dlg))
            bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            bb.rejected.connect(dlg.reject);l.addWidget(bb)
            dlg.exec()
        t=FnThread(fetch);t.done.connect(on_done);self._keep(t);t.start()

    def _open_catchup_picker(self,ch,parent=None):
        import datetime as _dt
        from PyQt6.QtWidgets import QDateTimeEdit
        from PyQt6.QtCore import QDateTime
        dlg=QDialog(parent or self);dlg.setWindowTitle(f"Archiwum: {ch.get('name','')}")
        dlg.resize(360,200);dlg.setStyleSheet(self.styleSheet())
        l=QVBoxLayout(dlg);l.setContentsMargins(14,14,14,14);l.setSpacing(8)
        l.addWidget(QLabel('Wybierz date i godzine:'))
        days=int(ch.get('tv_archive_duration',ch.get('catchup_days',7)) or 7)
        dt_edit=QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3600))
        dt_edit.setMinimumDateTime(QDateTime.currentDateTime().addDays(-days))
        dt_edit.setMaximumDateTime(QDateTime.currentDateTime())
        dt_edit.setDisplayFormat('dd.MM.yyyy HH:mm')
        dt_edit.setFixedHeight(32)
        l.addWidget(dt_edit)
        l.addWidget(QLabel(f'Dostepne: ostatnie {days} dni'))
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept);bb.rejected.connect(dlg.reject);l.addWidget(bb)
        if dlg.exec()!=QDialog.DialogCode.Accepted:return
        dt=dt_edit.dateTime().toPyDateTime()
        c=self._creds
        if not c:return
        sid=str(ch.get('stream_id',''))
        start_str=dt.strftime('%Y-%m-%d:%H-%M')
        dur=7200
        url=(f"{c['server'].rstrip('/')}/streaming/timeshift.php"
             f"?username={c['user']}&password={c['pass']}"
             f"&stream={sid}&start={start_str}&duration={dur}")
        name=f"{ch.get('name','')} [{dt.strftime('%d.%m %H:%M')}]"
        self._play(url,name)
        if parent:parent.accept()

    def _check_schedule(self):
        import datetime as _dt
        now=_dt.datetime.now()
        sched=load_json(SCHED_F) or []
        changed=False
        for r in sched:
            if r.get('done'):continue
            try:
                start=_dt.datetime.fromisoformat(r['start'])
                end=_dt.datetime.fromisoformat(r['end'])
                key=r.get('id',r['start'])
                active_proc=self._active_recs.get(key)
                if active_proc is None and start<=now<end:
                    # Time to start
                    proc=self._start_sched_rec(r)
                    if proc:self._active_recs[key]=proc
                    r['active']=True;changed=True
                    self.sb2.showMessage(f'⏺ Nagrywanie: {r.get("title","?")}')
                elif active_proc is not None and now>=end:
                    # Time to stop
                    try:active_proc.terminate()
                    except:pass
                    self._active_recs.pop(key,None)
                    self._save_sched_rec(r)
                    r['done']=True;r['active']=False;changed=True
                    self.sb2.showMessage(f'✔ Nagrano: {r.get("title","?")}')
                elif active_proc is not None:
                    # Check if process still alive
                    if active_proc.poll() is not None:
                        self._active_recs.pop(key,None)
                        r['active']=False;changed=True
            except:pass
        if changed:save_json(SCHED_F,sched)

    def _start_sched_rec(self,r):
        """Start scheduled recording, returns process object."""
        import subprocess as _sp
        url=r.get('url','')
        if not url:return None
        ff=os.path.join(os.path.dirname(os.path.abspath(__file__)),'ffmpeg.exe')
        if not os.path.isfile(ff):
            import shutil;ff=shutil.which('ffmpeg') or ''
        if not ff:return None
        name=re.sub(r'[<>:"/\\|?*]','_',r.get('title','nagranie'))
        ts=r.get('start','')[:16].replace(':','-').replace(' ','_')
        out=str(REC_DIR/f'{name}_{ts}.ts')
        r['out_file']=out
        try:
            proc=_sp.Popen([ff,'-i',url,'-c','copy','-y',out],
                stdout=_sp.DEVNULL,stderr=_sp.DEVNULL)
            return proc
        except Exception as e:
            self.sb2.showMessage(f'Blad nagrywania: {e}')
            return None

    def _stop_sched_rec(self,r):
        """Legacy: stop and save."""
        self._save_sched_rec(r)

    def _save_sched_rec(self,r):
        import time as _t
        import datetime as _dt
        f=r.get('out_file','')
        if f and os.path.isfile(f):
            try:
                s=_dt.datetime.fromisoformat(r.get('start','1970-01-01T00:00:00'))
                e=_dt.datetime.fromisoformat(r.get('end','1970-01-01T00:00:00'))
                dur=int((e-s).total_seconds())
            except:dur=0
            recs=load_json(REC_F) or []
            recs=[x for x in recs if x.get('file')!=f]  # avoid duplicate
            recs.insert(0,{'file':f,'name':r.get('title',r.get('ch_name','?')),
                           'ch':r.get('ch_name',''),'dur':dur,'ts':_t.time(),'from_sched':True})
            save_json(REC_F,recs)

    def _show_guide(self):
        """EPG guide with scheduling. Fetch full day EPG for live channels."""
        if not self._creds:
            QMessageBox.warning(self,'Brak połączenia','Najpierw połącz się z serwerem')
            return
        # Get channels from current live streams or favorites
        channels=[]
        if self._tab=='live' and self._filtered:
            channels=[ch for ch in self._filtered[:50] if isinstance(ch,dict)]
        elif self._favs.get('live') and self._streams:
            favs=self._favs['live']
            channels=[ch for ch in self._streams if str(ch.get('stream_id','')) in favs][:50]
        if not channels:
            QMessageBox.information(self,'Przewodnik','Przejdź na zakładkę Live i wybierz kategorię')
            return

        dlg=QDialog(self);dlg.setWindowTitle('📅 Przewodnik TV i Planowanie nagrań')
        dlg.resize(980,620);dlg.setStyleSheet(self.styleSheet())
        l=QVBoxLayout(dlg);l.setContentsMargins(8,8,8,8);l.setSpacing(6)

        # Header: date selector + info
        hdr=QHBoxLayout()
        import datetime as _dt
        today=_dt.date.today()
        hdr.addWidget(QLabel('Data:'))
        date_combo=QComboBox()
        for i in range(7):
            d=today+_dt.timedelta(days=i)
            date_combo.addItem(d.strftime('%d.%m.%Y  (%A)'),d.isoformat())
        hdr.addWidget(date_combo);hdr.addStretch()
        b_load=QPushButton('Pobierz EPG');b_load.setFixedHeight(26)
        hdr.addWidget(b_load)
        l.addLayout(hdr)

        # Scheduled recordings panel (top)
        sched_w=QWidget();sched_w.setStyleSheet('background:#0a0a16;border-radius:4px;')
        sched_l=QHBoxLayout(sched_w);sched_l.setContentsMargins(8,4,8,4)
        sched_l.addWidget(QLabel('Zaplanowane:'))
        sched_list=QLabel('Ładowanie...');sched_list.setStyleSheet('color:#7c6af7;font-size:11px;')
        sched_l.addWidget(sched_list,1)
        b_sched_view=QPushButton('Zarządzaj');b_sched_view.setFixedHeight(22)
        b_sched_view.clicked.connect(lambda:self._manage_schedule(dlg))
        sched_l.addWidget(b_sched_view)
        l.addWidget(sched_w)

        # Main: channel list left + program table right
        main_split=QSplitter(Qt.Orientation.Horizontal)

        # Channel list (left)
        ch_list=QListWidget()
        ch_list.setMaximumWidth(180)
        ch_list.setStyleSheet('QListWidget{background:#0a0a10;}QListWidget::item{padding:5px 8px;}QListWidget::item:selected{background:#1e1e3a;color:#fff;}')
        for ch in channels:
            it=QListWidgetItem(ch.get('name','')[:24])
            it.setData(Qt.ItemDataRole.UserRole,ch)
            ch_list.addItem(it)
        main_split.addWidget(ch_list)

        # Program list (right)
        prog_area=QWidget()
        prog_layout=QVBoxLayout(prog_area);prog_layout.setContentsMargins(0,0,0,0);prog_layout.setSpacing(4)
        prog_hdr=QLabel('Wybierz kanał →');prog_hdr.setStyleSheet('color:#555;padding:8px;')
        prog_layout.addWidget(prog_hdr)
        prog_list=QListWidget()
        prog_list.setStyleSheet(
            'QListWidget{background:#080810;}QListWidget::item{padding:8px 12px;border-bottom:1px solid #1a1a22;}'
            'QListWidget::item:selected{background:#1e2040;color:#fff;border-left:3px solid #c41e3a;}'
            'QListWidget::item:hover{background:#12121e;}')
        prog_layout.addWidget(prog_list,1)
        # Action buttons
        act_row=QHBoxLayout()
        b_rec_prog=QPushButton('⏺ Zaplanuj nagranie');b_rec_prog.setFixedHeight(28)
        b_rec_prog.setStyleSheet('background:#1a0000;color:#ff4444;border-color:#440000;')
        b_rec_prog.setEnabled(False)
        b_watch=QPushButton('▶ Oglądaj teraz');b_watch.setFixedHeight(28);b_watch.setEnabled(False)
        act_row.addWidget(b_rec_prog);act_row.addWidget(b_watch);act_row.addStretch()
        prog_layout.addLayout(act_row)
        main_split.addWidget(prog_area)
        main_split.setSizes([180,780])
        l.addWidget(main_split,1)

        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject);l.addWidget(bb)

        # Update scheduled display
        def refresh_sched_display():
            sched=load_json(SCHED_F) or []
            active=[r for r in sched if not r.get('done')]
            if active:
                sched_list.setText('  |  '.join(f"{r.get('ch_name','?')} — {r.get('title','?')}" for r in active[:4]))
            else:
                sched_list.setText('Brak zaplanowanych nagrań')
        refresh_sched_display()

        # Load EPG for selected channel
        def on_ch_sel():
            it=ch_list.currentItem()
            if not it:return
            ch=it.data(Qt.ItemDataRole.UserRole)
            sid=str(ch.get('stream_id',''))
            name=ch.get('name','')
            date_str=date_combo.currentData()
            prog_hdr.setText(f'Pobieranie EPG dla {name}...')
            prog_list.clear();b_rec_prog.setEnabled(False);b_watch.setEnabled(False)
            _c=self._creds
            def fetch():
                import datetime as _dt2
                result=[]
                try:
                    # Try get_short_epg with higher limit first
                    # XC API: get_epg_listings returns upcoming programs
                    # limit is often ignored - returns 4-10 items max
                    url=xc_base(_c)+f'&action=get_epg_listings&stream_id={sid}&limit=200'
                    raw=http_get(url,timeout=10)
                    d=json.loads(raw)
                    items=d.get('epg_listings',[])
                    if not items:
                        url2=xc_base(_c)+f'&action=get_short_epg&stream_id={sid}&limit=200'
                        d2=json.loads(http_get(url2,timeout=10))
                        items=d2.get('epg_listings',[])
                    import time as _tm
                    local_offset=_tm.timezone  # seconds west of UTC
                    for ep in items:
                        try:
                            start_s=ep.get('start','')
                            end_s=ep.get('end','')
                            # Parse - XC uses local time in most servers
                            s=_dt2.datetime.fromisoformat(start_s.replace(' ','T'))
                            e=_dt2.datetime.fromisoformat(end_s.replace(' ','T'))
                                    # Accept all - server often returns current + next few
                            if True:
                                result.append({'title':b64d(ep.get('title','')),
                                               'desc':b64d(ep.get('description','')),
                                               'start':start_s,'end':end_s,
                                               'start_dt':s,'end_dt':e,
                                               'ch':ch,'sid':sid})
                        except:pass
                except Exception as ex:
                    result=[('ERR',str(ex))]  # signal error to on_done
                return result
            def on_done(progs):
                import datetime as _dt3
                now=_dt3.datetime.now()
                prog_list.clear()
                # Check for error signal
                if progs and isinstance(progs[0],tuple) and progs[0][0]=='ERR':
                    prog_hdr.setText(f'{name} — BLAD: {progs[0][1]}')
                    return
                if not progs:
                    prog_hdr.setText(f'{name} — brak danych EPG')
                    return
                prog_hdr.setText(f'{name} — {len(progs)} programów (EPG)')
                for p in sorted(progs,key=lambda x:x.get('start','')):
                    try:
                        s=p['start_dt'];e=p['end_dt']
                        dur=int((e-s).total_seconds()//60)
                        time_str=s.strftime('%H:%M')
                        status=''
                        if s<=now<=e:status=' ▶ TERAZ'
                        elif s>now:status=''
                        else:status=' ✓'
                        it2=QListWidgetItem(f"{time_str}  {p['title'][:50]}  ({dur}min){status}")
                        it2.setData(Qt.ItemDataRole.UserRole,p)
                        if status==' ▶ TERAZ':
                            it2.setForeground(QColor('#c41e3a'))
                            it2.setFont(__import__('PyQt6.QtGui',fromlist=['QFont']).QFont('Segoe UI',10,700))
                        prog_list.addItem(it2)
                    except:pass
                b_rec_prog.setEnabled(True);b_watch.setEnabled(True)
            t=FnThread(fetch);t.done.connect(on_done);self._keep(t);t.start()
        ch_list.itemSelectionChanged.connect(on_ch_sel)
        date_combo.currentIndexChanged.connect(lambda _:on_ch_sel() if ch_list.currentItem() else None)
        b_load.clicked.connect(on_ch_sel)

        # Schedule recording
        def schedule_rec():
            it2=prog_list.currentItem()
            if not it2:return
            p=it2.data(Qt.ItemDataRole.UserRole)
            import datetime as _dt4
            ch=p.get('ch',{})
            url=self._url(ch)
            if not url:QMessageBox.warning(dlg,'Brak URL','Nie można uzyskać URL kanału');return
            start_dt=p['start_dt'];end_dt=p['end_dt']
            now=_dt4.datetime.now()
            # Confirm dialog
            dur=int((end_dt-start_dt).total_seconds()//60)
            status_warn='UWAGA: Program juz trwa!' if start_dt<=now else ''
            msg=f'Kanal: {ch.get("name","?")} | {p["title"]} | {start_dt.strftime("%d.%m %H:%M")}-{end_dt.strftime("%H:%M")} ({dur}min) {status_warn}'
            if QMessageBox.question(dlg,'Zaplanować nagranie?',msg)!=QMessageBox.StandardButton.Yes:return
            sched=load_json(SCHED_F) or []
            entry={'id':f"{p['sid']}_{p['start']}",
                   'ch_name':ch.get('name','?'),
                   'title':p['title'],
                   'start':start_dt.isoformat(),
                   'end':end_dt.isoformat(),
                   'url':url,'done':False,'active':False}
            # Remove duplicate
            sched=[r for r in sched if r.get('id')!=entry['id']]
            sched.append(entry);save_json(SCHED_F,sched)
            it2.setText(it2.text().rstrip('📌')+' 📌')
            it2.setForeground(QColor('#7c6af7'))
            self.sb2.showMessage(f"Zaplanowano: {p['title']} @ {start_dt.strftime('%H:%M')}")
            refresh_sched_display()
        b_rec_prog.clicked.connect(schedule_rec)

        def watch_now():
            it2=prog_list.currentItem()
            if not it2:return
            p=it2.data(Qt.ItemDataRole.UserRole)
            ch=p.get('ch',{})
            url=self._url(ch)
            if not url:return
            self._play(url,ch.get('name',''))
            sid=str(ch.get('stream_id',''))
            name_ch=ch.get('name','')
            # Set EPG from guide data immediately
            epg_data={'title':p.get('title',''),'desc':p.get('desc',''),
                      'start':p.get('start',''),'end':p.get('end',''),
                      'next':''}
            self._epg[sid]=epg_data
            self._show_epg_bar(epg_data)
            self.epg_bar.show()
            self.info_title.setText(epg_data['title'])
            self.info_meta.setText(name_ch)
            self.info_plot.setText(p.get('desc','')[:300])
            self.info_w.show()
            # Also fetch fresh EPG
            QTimer.singleShot(500,lambda s=sid,n=name_ch:self._fetch_epg(s,n))
            dlg.accept()
        b_watch.clicked.connect(watch_now)
        prog_list.itemDoubleClicked.connect(lambda it3:(prog_list.setCurrentItem(it3),watch_now()))

        dlg.exec()

    def _manage_schedule(self,parent=None):
        """View and manage scheduled recordings."""
        sched=load_json(SCHED_F) or []
        dlg=QDialog(parent or self);dlg.setWindowTitle('Zaplanowane nagrania')
        dlg.resize(650,400);dlg.setStyleSheet(self.styleSheet())
        l=QVBoxLayout(dlg);l.setContentsMargins(10,10,10,10);l.setSpacing(6)
        lst=QListWidget()
        lst.setStyleSheet('QListWidget{background:#080810;}QListWidget::item{padding:8px 12px;border-bottom:1px solid #1a1a22;}QListWidget::item:selected{background:#1e1e3a;color:#fff;}')
        import datetime as _dt
        def refresh():
            lst.clear()
            for r in sched:
                if r.get('done'):continue
                try:s=_dt.datetime.fromisoformat(r['start']);e=_dt.datetime.fromisoformat(r['end'])
                except:continue
                now=_dt.datetime.now()
                if r.get('active'):st='⏺ NAGRYWA'
                elif s>now:st=f"⏰ {s.strftime('%d.%m %H:%M')}"
                else:st='oczekuje'
                dur=int((e-s).total_seconds()//60)
                it=QListWidgetItem(f"{st}  {r.get('ch_name','?')} — {r.get('title','?')}  ({dur}min)")
                it.setData(Qt.ItemDataRole.UserRole,r)
                if r.get('active'):it.setForeground(QColor('#c41e3a'))
                lst.addItem(it)
        refresh()
        l.addWidget(lst,1)
        btns=QHBoxLayout()
        b_del=QPushButton('Usuń zaznaczone');b_del.setFixedHeight(26)
        b_del_done=QPushButton('Usuń wykonane');b_del_done.setFixedHeight(26)
        btns.addWidget(b_del);btns.addWidget(b_del_done);btns.addStretch()
        l.addLayout(btns)
        def del_sel():
            it=lst.currentItem()
            if not it:return
            r=it.data(Qt.ItemDataRole.UserRole)
            sched2=[x for x in(load_json(SCHED_F) or []) if x.get('id')!=r.get('id')]
            save_json(SCHED_F,sched2);sched.clear();sched.extend(sched2);refresh()
        def del_done():
            sched2=[x for x in(load_json(SCHED_F) or []) if not x.get('done')]
            save_json(SCHED_F,sched2);sched.clear();sched.extend(sched2);refresh()
        b_del.clicked.connect(del_sel);b_del_done.clicked.connect(del_done)
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject);l.addWidget(bb)
        dlg.exec()

    def _on_media_status(self,status):
        if status==QMediaPlayer.MediaStatus.EndOfMedia and self._tab=='series':
            # Auto-next episode
            QTimer.singleShot(3000,self._auto_next_episode)

    def _auto_next_episode(self):
        if not self._cur_ep_list or self._cur_ep_idx is None:return
        nxt=self._cur_ep_idx+1
        if nxt<len(self._cur_ep_list):
            self.sb2.showMessage('Nastepny odcinek za 3s...')
            ep=self._cur_ep_list[nxt]
            c=self._creds;self._cur_ep_idx=nxt
            eid=ep.get('id','');ext=ep.get('container_extension','mkv')
            if c and eid:
                url=f"{c['server'].rstrip('/')}/series/{c['user']}/{c['pass']}/{eid}.{ext}"
                series_name=getattr(self,'_cur_series_name','')
                num=ep.get('episode_num',nxt+1)
                title=ep.get('title',f'Odcinek {num}')
                self._play(url,f'{series_name} E{num} — {title}')
                # Save progress
                if self._cur_ch:
                    sid=str(self._cur_ch.get('series_id','') or self._cur_ch.get('stream_id',''))
                    self._series_progress[sid]={'ep_idx':nxt,'ep_num':num,'season':getattr(self,'_cur_ep_season','1')}
                    save_json(APP_DIR/'series_progress.json',self._series_progress)

    def _on_info_dbl(self):
        """Double-click on info panel = play/open current item."""
        if not self._cur_ch:return
        if self._tab=='series':self._open_series(self._cur_ch)
        else:
            url=self._url(self._cur_ch)
            if url:self._play(url,self._cur_ch.get('name',''))

    def _open_trailer(self):
        t=getattr(self,'_cur_trailer','')
        if not t:return
        # YouTube URLs - open in browser; direct video URLs - play in player
        if 'youtube.com' in t or 'youtu.be' in t:
            import webbrowser;webbrowser.open(t)
        else:
            # Direct video stream - play in player
            name=getattr(self,'_cur_ch',{}).get('name','Trailer') if self._cur_ch else 'Trailer'
            self._play(t,f'[Trailer] {name}')

    def _open_imdb(self):
        q=getattr(self,'_cur_imdb_id','') or getattr(self,'_cur_imdb_q','')
        if q:
            import webbrowser
            url=f'https://www.imdb.com/title/{q}' if q.startswith('tt') else f'https://www.imdb.com/find?q={q.replace(" ","+")}'
            webbrowser.open(url)

    def _load_img(self,url,label,w=70,h=98):
        req=QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute,False)
        reply=self._nam.get(req)
        def done():
            try:
                if reply.error()==QNetworkReply.NetworkError.NoError:
                    px=QPixmap();px.loadFromData(reply.readAll())
                    if not px.isNull():
                        px=px.scaled(w,h,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
                        label.setPixmap(px);label.show()
            except RuntimeError:pass  # widget deleted before image arrived
            finally:
                try:reply.deleteLater()
                except:pass
        reply.finished.connect(done)

    def _find_ffprobe(self):
        import shutil
        for n in("ffprobe","ffprobe.exe"):
            p=shutil.which(n)
            if p:return p
        base=os.path.dirname(os.path.abspath(__file__))
        for p in[os.path.join(base,"ffprobe.exe"),r"C:\ffmpeg\bin\ffprobe.exe"]:
            if os.path.isfile(p):return p
        return None

    def _open_series(self,ch):
        if not self._creds:return
        sid=str(ch.get("series_id","") or ch.get("stream_id",""))
        c=self._creds
        self.sb2.showMessage(f"Pobieranie odcinkow: {ch.get('name','')}")
        meta=self._series_langs.get(sid,{})
        self.info_cover.setPixmap(QPixmap());self.info_cover.hide()
        self.info_title.setText(ch.get("name",""))
        p=[]
        try:
            rt=meta.get("rating") or ch.get("rating","")
            if rt:p.append(f"* {float(str(rt).replace(',','.')):.1f}")
        except:pass
        g=meta.get("genre") or ch.get("genre","")
        if g:p.append(str(g))
        self.info_meta.setText("  |  ".join(p))
        self.info_plot.setText(str(meta.get("plot") or ch.get("plot","") or "")[:300])
        cover=ch.get("cover","") or ch.get("stream_icon","")
        if cover:self._load_img(cover,self.info_cover,70,98)
        trailer=meta.get("trailer") or ch.get("youtube_trailer","")
        if trailer:self._cur_trailer=trailer;self.info_trailer.show()
        else:self._cur_trailer="";self.info_trailer.hide()
        self.info_w.show()
        def fetch():
            return json.loads(http_get(xc_base(c)+f"&action=get_series_info&series_id={sid}"))
        def ok(data):
            self.sb2.showMessage("")
            info=data.get("info",{}) or {}
            if info.get("plot"):self.info_plot.setText(info["plot"][:400])
            if info.get("youtube_trailer") and not self._cur_trailer:
                self._cur_trailer=info["youtube_trailer"];self.info_trailer.show()
            dlg=EpsDlg(ch,data,self._creds,self)
            dlg.play_sig.connect(self._play)
            dlg.exec()
        def err(e):self.sb2.showMessage(f"Blad: {e}")
        t=FnThread(fetch);t.done.connect(ok);t.err.connect(err);self._keep(t);t.start()

    def _on_audio_track(self,idx):
        if idx>=0:QTimer.singleShot(0,lambda i=idx:self._do_audio(i))

    def _do_audio(self,i):
        try:self.player.setActiveAudioTrack(i)
        except:pass

    def _do_sub(self,i):
        try:self.player.setActiveSubtitleTrack(i)
        except:pass

    def _show_tracks(self):
        if not self._cur_ch:self.sb2.showMessage('Brak aktywnego strumienia');return
        # Use stored URL (works for series episodes where _url returns None)
        url=getattr(self,'_cur_url',None) or self._url(self._cur_ch)
        if not url:self.sb2.showMessage('Brak URL strumienia');return
        ff=self._find_ffprobe()
        if not ff:self.sb2.showMessage("Brak ffprobe.exe - wrzuc obok playera");return
        self.sb2.showMessage("Czytam sciezki...")
        cur=self._cur_ch
        def probe():
            import subprocess as _sp,json as _j
            try:
                r=_sp.run([ff,"-v","quiet","-print_format","json","-show_streams","-i",url],
                    capture_output=True,timeout=10)
                d=_j.loads(r.stdout or b"{}")
                audio=[];subs=[]
                for s in d.get("streams",[]):
                    tags=s.get("tags",{})
                    lang=(tags.get("language") or tags.get("LANGUAGE") or tags.get("title") or "").strip()
                    codec=s.get("codec_name","")
                    name=(lang or codec).upper() or "Track"
                    if s.get("codec_type")=="audio":audio.append({"n":name,"l":lang.lower(),"i":len(audio)})
                    elif s.get("codec_type")=="subtitle":subs.append({"n":name,"l":lang.lower(),"i":len(subs)})
                return {"audio":audio,"subs":subs}
            except Exception as e:return {"audio":[],"subs":[],"err":str(e)}
        def on_done(r):
            if self._cur_ch is not cur:return
            if r.get("err"):self.sb2.showMessage(f"Blad: {r['err']}");return
            audio=r["audio"];subs=r["subs"]
            self.audio_sel.blockSignals(True);self.audio_sel.clear()
            pl=-1
            for t in audio:
                self.audio_sel.addItem(t["n"])
                if pl<0 and t["l"] in("pol","pl","polish","plk"):pl=t["i"]
            if audio:
                sel=pl if pl>=0 else 0
                self.audio_sel.setCurrentIndex(sel);self.audio_sel.show();self.audio_lbl.show()
                QTimer.singleShot(200,lambda i=sel:self._do_audio(i))
            self.audio_sel.blockSignals(False)
            self.sub_sel.blockSignals(True);self.sub_sel.clear()
            self.sub_sel.addItem("Brak napisow")
            pl_s=-1
            for t in subs:
                self.sub_sel.addItem(t["n"])
                if pl_s<0 and t["l"] in("pol","pl","polish","plk"):pl_s=t["i"]
            if subs:
                if pl_s>=0 and pl<0:
                    self.sub_sel.setCurrentIndex(pl_s+1)
                    QTimer.singleShot(200,lambda i=pl_s:self._do_sub(i))
                self.sub_sel.show();self.sub_lbl.show()
            self.sub_sel.blockSignals(False)
            pl=" PL+" if pl>=0 else (" sub PL+" if pl_s>=0 else "")
            self.sb2.showMessage(f"Audio:{len(audio)} Sub:{len(subs)}{pl}")
        t=FnThread(probe);t.done.connect(on_done);self._keep(t);t.start()

    def _scan_start(self):
        if self._tab=="live":return
        ff=self._find_ffprobe()
        if not ff:self.sb2.showMessage("Brak ffprobe.exe - wrzuc obok playera");return
        source=list(self._filtered) if hasattr(self,"_filtered") and self._filtered else []
        if not source:self.sb2.showMessage("Brak pozycji - wybierz folder");return
        cache=self._series_langs if self._tab=="series" else self._langs
        items=[ch for ch in source if isinstance(ch,dict)
               and str(ch.get("stream_id") or ch.get("series_id","")) not in cache]
        if not items:self.sb2.showMessage(f"Wszystkie {len(source)} zeskanowane.");return
        self.sb2.showMessage(f"Skanowanie {len(items)} z {len(source)}...")
        self._scan_abort=False;self._scan_q=items[:]
        self._scan_done=0;self._scan_tot=len(items);self._ff=ff
        self.sbar.show();self.scan_prg.setRange(0,len(items));self._scan_next()

    def _scan_one(self,ch):
        ff=self._find_ffprobe()
        if not ff:self.sb2.showMessage("Brak ffprobe.exe");return
        if not isinstance(ch,dict):return
        self._scan_abort=False;self._scan_q=[ch]
        self._scan_done=0;self._scan_tot=1;self._ff=ff
        self.sbar.show();self.scan_prg.setRange(0,1);self._scan_next()

    def _scan_next(self):
        while True:
            if self._scan_abort or not self._scan_q:self._scan_finish();return
            ch=self._scan_q.pop(0)
            if not isinstance(ch,dict):self._scan_done+=1;continue
            sid=str(ch.get("stream_id") or ch.get("series_id",""))
            # For vod: url is direct; for series: resolved in thread
            url=self._url(ch)  # None for series - resolved in probe thread
            if not url and self._tab!="series":self._scan_done+=1;continue
            break
        self.scan_lbl.setText(f"[{self._scan_done}/{self._scan_tot}] {ch.get('name','')[:40]}")
        self.scan_prg.setValue(self._scan_done)
        ff=self._ff;c=self._creds;tab=self._tab
        def probe():
            import subprocess as _sp,json as _j
            res={"audio":[],"subs":[],"ok":True}
            # Resolve series URL in thread (blocking HTTP is OK here)
            scan_url=url
            if tab=="series" and not scan_url and c:
                try:
                    d=_j.loads(http_get(xc_base(c)+f"&action=get_series_info&series_id={sid}"))
                    eps=d.get("episodes",{})
                    for season in sorted(eps.keys(),key=lambda x:(int(x) if str(x).isdigit() else 999)):
                        if eps[season]:
                            ep=eps[season][0];eid=ep.get("id","");ext=ep.get("container_extension","mkv")
                            if eid:scan_url=f"{c['server'].rstrip('/')}/series/{c['user']}/{c['pass']}/{eid}.{ext}";break
                    # Also store XC info while we have it
                    info=d.get("info",{}) or {}
                    res["xc"]={"rating":str(info.get("rating","") or ""),"genre":str(info.get("genre","") or ""),
                               "plot":str(info.get("plot","") or ""),"cover":str(info.get("cover","") or ""),
                               "trailer":str(info.get("youtube_trailer","") or "")}
                except:pass
            if not scan_url:return res  # no url found
            try:
                r=_sp.run([ff,"-v","quiet","-print_format","json","-show_streams","-i",scan_url],
                    capture_output=True,timeout=12)
                d=_j.loads(r.stdout or b"{}")
                for s in d.get("streams",[]):
                    tags=s.get("tags",{})
                    lang=(tags.get("language") or tags.get("LANGUAGE") or tags.get("title") or s.get("codec_name","")).lower().strip()
                    lang=lang or f"{s.get('codec_type','?')}{s.get('index',0)}"
                    if s.get("codec_type")=="audio":res["audio"].append(lang)
                    elif s.get("codec_type")=="subtitle":res["subs"].append(lang)
            except:pass
            if c and tab=="vod":
                try:
                    mi=_j.loads(http_get(xc_base(c)+f"&action=get_vod_info&vod_id={sid}",timeout=5)).get("info",{})
                    res["xc"]={"rating":str(mi.get("rating","") or ""),"duration":str(mi.get("duration","") or ""),
                               "genre":str(mi.get("genre","") or ""),"year":str(mi.get("year","") or ""),
                               "plot":str(mi.get("plot","") or mi.get("description","") or ""),
                               "trailer":str(mi.get("youtube_trailer","") or "")}
                except:pass
            return res
        def on_done(res):
            aL=res.get("audio",[]); sL=res.get("subs",[])
            m={"audio":aL,"subs":sL,
               "plAudio":any(l in("pol","pl","polish","plk") for l in aL),
               "plSubs":any(l in("pol","pl","polish","plk") for l in sL)}
            for k,v in res.get("xc",{}).items():
                if v:m[k]=v
            cache=self._series_langs if tab=="series" else self._langs
            cache[sid]=m
            save_json(APP_DIR/"series_lang.json" if tab=="series" else LANG_F, cache)
            for i in range(self.clist.count()):
                it=self.clist.item(i); c2=it.data(Qt.ItemDataRole.UserRole)
                if not isinstance(c2,dict):continue
                if str(c2.get("stream_id") or c2.get("series_id",""))==sid:
                    # Badge: PL first, all langs
                    has_pl=any(l in("pol","pl","polish","plk") for l in aL)
                    has_pl_s=any(l in("pol","pl","polish","plk") for l in sL)
                    if has_pl:
                        pl_a=[l.upper() for l in aL if l in("pol","pl","polish","plk")]
                        oth=[l.upper() for l in aL if l not in("pol","pl","polish","plk")]
                        lang_badge=" ●"+",".join(pl_a)+("+" + ",".join(oth) if oth else "")
                    elif aL:
                        lang_badge=" ["+ ",".join(l.upper() for l in aL)+ "]"
                    else:
                        lang_badge=""
                    if has_pl_s:lang_badge+="○"
                    elif sL:lang_badge+=" ("+ ",".join(l.upper() for l in sL)+ ")"
                    it.setText(c2.get("name","")+lang_badge)
                    break
            self._scan_done+=1;self._scan_next()
        t=FnThread(probe);t.done.connect(on_done);self._keep(t);t.start()

    def _series_ep1(self,ch):
        if not self._creds:return None
        try:
            c=self._creds;sid=str(ch.get("series_id","") or ch.get("stream_id",""))
            d=json.loads(http_get(xc_base(c)+f"&action=get_series_info&series_id={sid}"))
            eps=d.get("episodes",{})
            for season in sorted(eps.keys(),key=lambda x:(int(x) if str(x).isdigit() else 999)):
                if eps[season]:
                    ep=eps[season][0];eid=ep.get("id","");ext=ep.get("container_extension","mkv")
                    if eid:return f"{c['server'].rstrip('/')}/series/{c['user']}/{c['pass']}/{eid}.{ext}"
        except:pass
        return None

    def _scan_abort_fn(self):self._scan_abort=True

    def _scan_finish(self):
        self.sbar.hide()
        save_json(LANG_F,self._langs)
        save_json(APP_DIR/"series_lang.json",self._series_langs)
        self.sb2.showMessage(f"Skanowanie: {self._scan_done} pozycji")

    def _fetch_movie(self,ch):
        sid=str(ch.get('stream_id') or ch.get('series_id',''))
        meta=(self._series_langs if self._tab=='series' else self._langs).get(sid,{})
        name=ch.get("name","")
        p=[]
        try:
            rt=meta.get("imdb") or meta.get("rating") or ch.get("rating") or ch.get("rating_5based","")
            if rt:p.append(f"* {float(str(rt).replace(',','.')):.1f}")
        except:pass
        g=meta.get("genre") or ch.get("genre","")
        if g:p.append(str(g))
        yr=meta.get("year") or str(ch.get("year","") or "")[:4]
        if yr:p.append(yr)
        dur=meta.get("duration","")
        if dur:p.append(str(dur))
        self.info_title.setText(name)
        self.info_meta.setText("  |  ".join(p))
        self.info_plot.setText(str(meta.get("plot") or ch.get("plot","") or ch.get("description","") or "")[:400])
        cover=ch.get("stream_icon","") or ch.get("cover","") or meta.get("cover","")
        if cover:self._load_img(cover,self.info_cover,70,98)
        else:self.info_cover.setPixmap(QPixmap());self.info_cover.hide()
        trailer=meta.get("trailer") or ch.get("youtube_trailer","")
        if trailer:self._cur_trailer=trailer;self.info_trailer.show()
        else:self._cur_trailer="";self.info_trailer.hide()
        self.info_w.show()
        if not self._cfg.get("omdb_key"):return
        title=re.sub(r"^[A-Z0-9]{1,6}\s*[-|:]\s+","",name)
        title=re.sub(r"\b(4K|HD|FHD|UHD|BluRay|WEB-DL|1080p|720p)\b","",title,flags=re.I)
        title=re.sub(r"\s*[\[\(][^\]\)]{1,30}[\]\)]","",title).strip()
        year=str(ch.get("year","") or "")[:4];key=self._cfg["omdb_key"]
        def fetch():
            q=quote_plus(title);y=f"&y={year}" if year else ""
            d=json.loads(http_get(f"https://www.omdbapi.com/?t={q}{y}&apikey={key}&plot=full",timeout=8))
            if d.get("Response")!="True":return None
            return{"rating":float(d.get("imdbRating",0) or 0),"plot":d.get("Plot",""),
                   "genre":d.get("Genre",""),"runtime":d.get("Runtime",""),
                   "imdb_id":d.get("imdbID","")}
        def on_done(info):
            if info and self._cur_ch and self._cur_ch.get("name")==name:
                p2=[]
                if info.get("rating"):p2.append(f"IMDB {info['rating']:.1f}")
                if info.get("genre"):p2.append(info["genre"])
                if info.get("runtime"):p2.append(info["runtime"])
                self.info_meta.setText("  |  ".join(p2))
                self.info_plot.setText((info.get("plot","") or "")[:400])
                if info.get("imdb_id"):self._cur_imdb_id=info["imdb_id"]
        t=FnThread(fetch);t.done.connect(on_done);self._keep(t);t.start()

    def _manage_cats(self):
        cats=self._cats.get(self._tab,[])
        if not cats:self.sb2.showMessage("Brak kategorii");return
        hidden=set(self._hidden_cats.get(self._tab,[]))
        dlg=QDialog(self);dlg.setWindowTitle("Zarzadzaj kategoriami")
        dlg.resize(280,480);dlg.setStyleSheet(self.styleSheet())
        l=QVBoxLayout(dlg);l.addWidget(QLabel("Odznacz = ukryj:"))
        br=QHBoxLayout()
        ba=QPushButton("Wszystkie");bn=QPushButton("Nic")
        br.addWidget(ba);br.addWidget(bn);l.addLayout(br)
        lst=QListWidget()
        for c in cats:
            cid=str(c.get("category_id",""))
            it=QListWidgetItem(c.get("category_name",""))
            it.setData(Qt.ItemDataRole.UserRole,cid)
            it.setCheckState(Qt.CheckState.Unchecked if cid in hidden else Qt.CheckState.Checked)
            lst.addItem(it)
        l.addWidget(lst,1)
        ba.clicked.connect(lambda:[lst.item(i).setCheckState(Qt.CheckState.Checked) for i in range(lst.count())])
        bn.clicked.connect(lambda:[lst.item(i).setCheckState(Qt.CheckState.Unchecked) for i in range(lst.count())])
        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept);bb.rejected.connect(dlg.reject);l.addWidget(bb)
        if dlg.exec()!=QDialog.DialogCode.Accepted:return
        new_h=[lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())
               if lst.item(i).checkState()==Qt.CheckState.Unchecked]
        self._hidden_cats[self._tab]=new_h
        save_json(APP_DIR/"hidden_cats.json",self._hidden_cats)
        self._pop_cats()
        # For vod/series: don't auto-load 'Wszystkie' (too slow)
        # For live: auto-load (or favs if available)
        if self.cat_list.count():
            if tab=='live':
                # Try to select favs first
                favs_row=0
                for i in range(self.cat_list.count()):
                    it=self.cat_list.item(i)
                    if it and it.data(Qt.ItemDataRole.UserRole)=='__favs__' and self._favs.get('live'):
                        favs_row=i;break
                self.cat_list.setCurrentRow(favs_row)
            else:
                # vod/series: select first real category (not __all__)
                for i in range(self.cat_list.count()):
                    it=self.cat_list.item(i)
                    if it and it.data(Qt.ItemDataRole.UserRole) not in('__all__','__favs__',None):
                        self.cat_list.setCurrentRow(i);break
                else:
                    self.cat_list.setCurrentRow(0)

    def _open(self):
        p,_=QFileDialog.getOpenFileName(self,"Otworz plik",os.path.expanduser("~"),"Media (*.mp4 *.mkv *.avi *.mov *.ts *.m3u8 *.mp3 *.flac)")
        if p:self._play(QUrl.fromLocalFile(p).toString(),os.path.basename(p))

    def _load_logo(self,url,item_ref):
        if url in self._logo_pending:return
        self._logo_pending[url]=True
        req=QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute,False)
        reply=self._nam.get(req)
        def on_done():
            self._logo_pending.pop(url,None)
            if reply.error()==QNetworkReply.NetworkError.NoError:
                px=QPixmap()
                px.loadFromData(reply.readAll())
                if not px.isNull():
                    px=px.scaled(32,32,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
                    icon=QIcon(px)
                    self._logo_cache[url]=icon
                    for i in range(self.clist.count()):
                        it=self.clist.item(i)
                        ch=it.data(Qt.ItemDataRole.UserRole)
                        if isinstance(ch,dict) and (ch.get("stream_icon") or ch.get("cover",""))==url:
                            it.setIcon(icon)
            reply.deleteLater()
        reply.finished.connect(on_done)

    def _keep(self,t):
        self._threads.append(t)
        t.finished.connect(lambda:self._threads.remove(t) if t in self._threads else None)

    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls():e.acceptProposedAction()
    def dropEvent(self,e):
        u=e.mimeData().urls()[0];p=u.toLocalFile()
        if p:self._play(QUrl.fromLocalFile(p).toString(),os.path.basename(p))

    def _toggle_grid_view(self,on):
        if on:
            self.clist.hide();self.grid_scroll.show()
            self._render_grid()
            # Fetch EPG for all visible channels in live grid
            if self._tab=='live' and self._filtered:
                QTimer.singleShot(200,lambda:self._fetch_epg_batch(self._filtered[:100]))
        else:
            self.grid_scroll.hide();self.clist.show()
            self.b_gridview.setChecked(False)

    def _fetch_epg_batch_list(self,channels):
        """Fetch EPG in 3 parallel threads for speed without throttle."""
        if not self._creds or not channels:return
        c=self._creds
        missing=[ch for ch in channels if isinstance(ch,dict)
                 and str(ch.get('stream_id','')) not in self._epg]
        if not missing:return
        # Split into 3 chunks for 3 parallel threads
        n=len(missing);chunk=max(1,n//3)
        chunks=[missing[:chunk],missing[chunk:2*chunk],missing[2*chunk:]]
        def fetch_chunk(items):
            import time as _t
            results={}
            for ch in items:
                sid=str(ch.get('stream_id',''))
                if not sid:continue
                try:
                    url=xc_base(c)+f'&action=get_short_epg&stream_id={sid}&limit=2'
                    d=json.loads(http_get(url,timeout=5))
                    lst=d.get('epg_listings',[])
                    if lst:
                        cur=lst[0];nxt=lst[1] if len(lst)>1 else {}
                        results[sid]={'title':b64d(cur.get('title','')),'desc':b64d(cur.get('description','')),
                                      'start':cur.get('start',''),'end':cur.get('end',''),
                                      'next':b64d(nxt.get('title','')) if nxt else ''}
                except:pass
                _t.sleep(0.08)
            return results
        def on_done(results):
            self._epg.update(results)
            for i in range(self.clist.count()):
                it=self.clist.item(i)
                if not it:continue
                ch2=it.data(Qt.ItemDataRole.UserRole)
                if not isinstance(ch2,dict):continue
                sid=str(ch2.get('stream_id',''))
                epg=self._epg.get(sid)
                if epg and epg.get('title'):
                    it.setText(f"{ch2.get('name','')}  \u25b6 {epg['title'][:35]}")
            if getattr(self,'b_gridview',None) and self.b_gridview.isChecked() and self._tab=='live':
                for sid,epg in results.items():
                    self._update_grid_epg(sid,epg)
        for ch_chunk in chunks:
            if not ch_chunk:continue
            t=FnThread(lambda items=ch_chunk:fetch_chunk(items))
            t.done.connect(on_done);self._keep(t);t.start()

    def _fetch_epg_batch(self,channels):
        """Fetch EPG for grid (reuse batch list logic)."""
        self._fetch_epg_batch_list(channels)

    def _update_grid_epg(self,sid,epg):
        title=epg.get('title','') if epg else ''
        nxt=epg.get('next','') if epg else ''
        for i in range(self.grid_layout.count()):
            cell=self.grid_layout.itemAt(i).widget()
            if not cell:continue
            if cell.property('stream_sid')==sid:
                # Update title bar
                try:
                    tb=cell.layout().itemAt(1).widget()
                    if tb:
                        lbl=tb.layout().itemAt(0).widget()
                        if lbl and title:
                            lbl.setText(title[:30])
                            lbl.setStyleSheet('color:#eee;font-size:10px;font-weight:bold;')
                except:pass
                # Update EPG overlay
                for child in cell.children():
                    if hasattr(child,'property') and child.property('stream_sid')==sid:
                        txt=title[:40]
                        if nxt:txt+=f'\n→ {nxt[:35]}'
                        try:child.setText(txt)
                        except:pass
                        break
                break

    def _grab_live_thumb(self,url,label,w=160,h=90):
        """Grab frame - cached, max 5 concurrent."""
        if len(self._thumb_in_progress)>=5:return  # rate limit
        if url in self._thumb_cache:
            try:label.setPixmap(self._thumb_cache[url]);label.show()
            except RuntimeError:pass
            return
        if url in self._thumb_in_progress:return
        self._thumb_in_progress.add(url)
        ff=os.path.join(os.path.dirname(os.path.abspath(__file__)),'ffmpeg.exe')
        if not os.path.isfile(ff):
            import shutil;ff=shutil.which('ffmpeg') or ''
        if not ff:self._thumb_in_progress.discard(url);return
        import tempfile;tmp=tempfile.mktemp(suffix='.jpg')
        def grab():
            import subprocess as _sp
            try:
                r=_sp.run([ff,'-ss','2','-i',url,'-vframes','1','-q:v','4',
                         '-vf',f'scale={w}:{h}','-y',tmp],
                    capture_output=True,timeout=8)
                return tmp if r.returncode==0 else None
            except:return None
        def on_done(path):
            self._thumb_in_progress.discard(url)
            if not path:return
            try:
                px=QPixmap(path)
                if not px.isNull():
                    self._thumb_cache[url]=px  # cache it
                    try:label.setPixmap(px);label.show()
                    except RuntimeError:pass
                try:os.remove(path)
                except:pass
            except:pass
        t=FnThread(grab);t.done.connect(on_done);self._keep(t);t.start()

    def _render_grid(self):
        """Render filtered streams as cover grid."""
        while self.grid_layout.count():
            w=self.grid_layout.takeAt(0).widget()
            if w:w.deleteLater()
        if not self._filtered:return
        is_live=self._tab=='live'
        avail_w=self.grid_scroll.width() or 640
        if is_live:
            cell_w=200;cell_h=140  # 16:9 thumbnail + title bar
            cover_h=112
        else:
            cell_w=180;cell_h=int(cell_w*1.55)
            cover_h=cell_h-36
        cols=max(2,avail_w//(cell_w+10))
        row=0;col=0
        for i,ch in enumerate(self._filtered[:300]):
            if not isinstance(ch,dict):continue
            cell=QWidget()
            cell.setFixedSize(cell_w,cell_h)
            cell.setStyleSheet('background:#111120;border-radius:8px;')
            cell.setCursor(Qt.CursorShape.PointingHandCursor)
            cl=QVBoxLayout(cell);cl.setContentsMargins(0,0,0,0);cl.setSpacing(0)
            # Cover image - no padding, fills top
            cover_lbl=QLabel()
            cover_lbl.setFixedSize(cell_w,cover_h)
            cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cover_lbl.setStyleSheet('background:#0d0d1a;border-radius:8px 8px 0 0;')
            cl.addWidget(cover_lbl)
            # Title bar at bottom
            title_bar=QWidget();title_bar.setFixedHeight(36)
            title_bar.setStyleSheet('background:#0a0a18;border-radius:0 0 8px 8px;')
            tbl2=QHBoxLayout(title_bar);tbl2.setContentsMargins(6,2,6,2)
            # Production year badge if available
            sid_g=str(ch.get('stream_id') or ch.get('series_id',''))
            meta_g=(self._series_langs if self._tab=='series' else self._langs).get(sid_g,{})
            yr_g=str(meta_g.get('year','') or ch.get('year','') or '')[:4]
            title_lbl=QLabel(ch.get('name','')[:22])
            title_lbl.setWordWrap(False)
            title_lbl.setStyleSheet('color:#dde;font-size:10px;')
            tbl2.addWidget(title_lbl,1)
            if yr_g:
                yr_lbl=QLabel(yr_g);yr_lbl.setStyleSheet('color:#666;font-size:9px;')
                tbl2.addWidget(yr_lbl)
            cl.addWidget(title_bar)
            # Load cover / thumbnail
            cover=ch.get('stream_icon','') or ch.get('cover','')
            if is_live:
                url_g=self._url(ch)
                # Stagger thumbnail loading: delay by position to avoid hammering
                delay=min(i*300,5000)  # 300ms per cell, max 5s
                if url_g:
                    QTimer.singleShot(delay,lambda u=url_g,l=cover_lbl:self._grab_live_thumb(u,l,cell_w,cover_h))
                if cover:self._load_img(cover,cover_lbl,cell_w,cover_h)  # logo shown immediately
                # Title bar: EPG program as primary, channel name small
                sid_g=str(ch.get('stream_id',''))
                epg_g=self._epg.get(sid_g)
                if epg_g and epg_g.get('title'):
                    title_lbl.setText(epg_g['title'][:30])
                    title_lbl.setStyleSheet('color:#eee;font-size:10px;font-weight:bold;')
                else:
                    # No EPG yet - show channel name smaller
                    title_lbl.setText(ch.get('name','')[:30])
                    title_lbl.setStyleSheet('color:#888;font-size:10px;')
            else:
                if cover:self._load_img(cover,cover_lbl,cell_w,cover_h)
            # Store sid for EPG update
            if is_live:cell.setProperty('stream_sid',str(ch.get('stream_id','')))
            # Live: semi-transparent EPG overlay on bottom of thumbnail
            if is_live:
                # Channel name top-left
                ch_name_lbl=QLabel(ch.get('name','')[:20])
                ch_name_lbl.setParent(cell)
                ch_name_lbl.setGeometry(0,0,cell_w,20)
                ch_name_lbl.setStyleSheet('color:#fff;font-size:9px;font-weight:bold;background:rgba(0,0,0,160);padding:2px 6px;')
                # EPG overlay bottom of thumbnail (will be updated when EPG loads)
                epg_overlay=QLabel('')
                epg_overlay.setParent(cell)
                epg_overlay.setGeometry(0,cover_h-38,cell_w,38)
                epg_overlay.setWordWrap(True)
                epg_overlay.setStyleSheet('color:#fff;font-size:9px;background:rgba(0,0,0,180);padding:3px 6px;')
                epg_overlay.setProperty('stream_sid',str(ch.get('stream_id','')))
                # Show cached EPG if available
                sid_e=str(ch.get('stream_id',''))
                epg_e=self._epg.get(sid_e)
                if epg_e and epg_e.get('title'):
                    epg_overlay.setText(epg_e['title'][:40])
            cell.mousePressEvent=lambda e,c=ch:self._on_grid_click(c)
            cell.mouseDoubleClickEvent=lambda e,c=ch:self._on_grid_dbl(c)
            self.grid_layout.addWidget(cell,row,col)
            col+=1
            if col>=cols:col=0;row+=1

    def _on_grid_click(self,ch):
        self._cur_ch=ch
        if self._tab=='live':
            # Show EPG info
            name_ch=ch.get('name','')
            sid=str(ch.get('stream_id',''))
            self.info_cover.setPixmap(QPixmap());self.info_cover.hide()
            self.info_trailer.hide();self._cur_trailer=''
            logo=ch.get('stream_icon','')
            if logo:self._load_img(logo,self.info_cover,52,52)
            epg=self._epg.get(sid)
            if epg:
                self.info_title.setText(epg.get('title',name_ch))
                self.info_meta.setText(name_ch)
                self.info_plot.setText(epg.get('desc','')[:300])
            else:
                self.info_title.setText(name_ch)
                self.info_meta.setText('Pobieranie EPG...')
                self.info_plot.setText('')
                self._fetch_epg(sid,name_ch)
            self.info_w.show()
        else:
            self.epg_bar.hide()
            self._fetch_movie(ch)

    def _on_grid_dbl(self,ch):
        self._cur_ch=ch
        if self._tab=='series':
            self._open_series(ch)
        else:
            url=self._url(ch)
            if url:self._play(url,ch.get('name',''))
            elif self._tab=='live':
                url2=self._url(ch)
                if url2:self._play(url2,ch.get('name',''))

    def _refresh_live_epg_filter(self):
        """Build genre filter from XC category names - reliable source."""
        if self._tab!='live':return
        # Group XC live categories by theme keywords
        # Each group = one filter option; stores matching category_ids
        GROUPS=[
            ('Sport',      ['sport','pilka nozna','football','soccer','tenis','tennis','koszykowka','siatkow','formula','f1','mma','boksk','liga','cup','puchar']),
            ('Filmy',      ['film','movie','kino','cinema','vod']),
            ('Seriale',    ['serial','series','sitcom']),
            ('Informacje', ['news','inform','wiadom','serwis','dziennik','fakty','panorama']),
            ('Dokumentalne',['dokument','document','histor','przyroda','nauka','discovery','national','geo','animal','wildlife']),
            ('Muzyka',     ['muzyk','music','mtv','disco','hit']),
            ('Rozrywka',   ['rozrywk','entertainment','show','kabaret','humor','comedy','talk']),
            ('Dla dzieci', ['dzieci','dziec','children','kids','junior','cartoon','bajk','animow','disney','nickel']),
            ('Religia',    ['religia','religious','catholic','katolic','tv trwam','ewangelia']),
        ]
        # Build category_id sets per group
        group_cats={}
        for group_name,keywords in GROUPS:
            ids=set()
            for cat in self._cats.get('live',[]):
                cname=cat.get('category_name','').lower()
                if any(kw in cname for kw in keywords):
                    ids.add(str(cat.get('category_id','')))
            if ids:group_cats[group_name]=ids
        self._live_group_cats=group_cats
        self.f_genre.blockSignals(True)
        cur=self.f_genre.currentText()
        self.f_genre.clear();self.f_genre.addItem('Wszystkie')
        for g in group_cats:self.f_genre.addItem(g)
        for i in range(self.f_genre.count()):
            if self.f_genre.itemText(i)==cur:self.f_genre.setCurrentIndex(i);break
        self.f_genre.blockSignals(False)
        self.f_genre.setVisible(bool(group_cats))

    def _refresh_epg(self):
        """Auto-refresh EPG for current live channel."""
        if self._tab=='live' and self._cur_ch:
            sid=str(self._cur_ch.get('stream_id',''))
            name=self._cur_ch.get('name','')
            self._fetch_epg(sid,name)

    def mouseMoveEvent(self,e):
        if self._fs:
            y=e.position().y() if hasattr(e,'position') else e.y()
            h=self.height()
            # Bottom 90px: show OSC
            if y>h-90 and self._osc_ref:
                self._osc_ref.show();self._osc_timer.start(3000)
            # Top 40% of screen: show EPG overlay
            if y<h*0.4 and self._tab=='live' and self._cur_ch:
                self._show_epg_overlay()
        super().mouseMoveEvent(e)

    def mouseDoubleClickEvent(self,e):
        if self.vcon.geometry().contains(e.pos()):self._toggle_fs()
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self,e):
        k=e.key();mod=e.modifiers()
        pos=self.player.position();dur=self.player.duration()
        if k==Qt.Key.Key_Space:
            if self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            else:self.player.play()
        elif k==Qt.Key.Key_F or k==Qt.Key.Key_Escape:
            if k==Qt.Key.Key_Escape and self._fs:self._toggle_fs()
            elif k==Qt.Key.Key_F:self._toggle_fs()
        elif k==Qt.Key.Key_M:
            self.player.setMuted(not self.player.isMuted())
        elif k==Qt.Key.Key_Right:
            if self._tab=='live':self._next()
            else:
                s=30000 if mod&Qt.KeyboardModifier.ShiftModifier else 5000
                self.player.setPosition(min(dur,pos+s))
        elif k==Qt.Key.Key_Left:
            if self._tab=='live':self._prev()
            else:
                s=30000 if mod&Qt.KeyboardModifier.ShiftModifier else 5000
                self.player.setPosition(max(0,pos-s))
        elif k==Qt.Key.Key_Up:
            if self._tab=='live':
                r=max(0,(self.clist.currentRow() or 0)-1)
                self.clist.setCurrentRow(r)
            else:self.vol.setValue(min(100,self.vol.value()+5))
        elif k==Qt.Key.Key_Down:
            if self._tab=='live':
                r=min(self.clist.count()-1,(self.clist.currentRow() or 0)+1)
                self.clist.setCurrentRow(r)
            else:self.vol.setValue(max(0,self.vol.value()-5))
        elif k in(Qt.Key.Key_Return,Qt.Key.Key_Enter):
            it=self.clist.currentItem()
            if it:self._on_dbl(it)
        elif k==Qt.Key.Key_N:self._next()
        elif k==Qt.Key.Key_P:self._prev()
        elif k==Qt.Key.Key_O:self._open()
        elif k==Qt.Key.Key_Q:self.close()
        elif k==Qt.Key.Key_R:
            rp=getattr(self,'_resume_pos',0)
            if rp>0:self.player.setPosition(rp);self.sb2.showMessage(f'Wznowiono od {fmt_t(rp)}')
        elif k==Qt.Key.Key_0:self.vol.setValue(0)
        elif Qt.Key.Key_1<=k<=Qt.Key.Key_9:
            self.vol.setValue((k-Qt.Key.Key_0)*10)
        else:super().keyPressEvent(e)

    def closeEvent(self,e):
        save_json(LANG_F,self._langs)
        save_json(APP_DIR/"series_lang.json",self._series_langs)
        self._save_favs();super().closeEvent(e)

if __name__=="__main__":
    import os
    os.environ["QT_LOGGING_RULES"] = "*=false"  # silence all Qt debug
    os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
    # Redirect stderr to devnull to kill FFmpeg noise
    import ctypes
    if sys.platform == "win32":
        try:
            devnull = open(os.devnull, 'w')
            import io
            sys.stderr = io.TextIOWrapper(io.FileIO(os.devnull, 'w'))
        except: pass
    try:
        import urllib3;urllib3.disable_warnings()
    except:pass
    app=QApplication(sys.argv)
    app.setApplicationName("IPTV Player")
    win=IPTVPlayer()
    if len(sys.argv)>1 and os.path.isfile(sys.argv[1]):
        win._play(QUrl.fromLocalFile(sys.argv[1]).toString(),sys.argv[1])
    win.show()
    sys.exit(app.exec())
