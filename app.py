# ============================================================
#  TikTok Live Recorder + Procesador de Audio
#  Versión 2.0  —  2 tabs integrados
#
#  TAB 1: Monitor  → graba lives de TikTok automáticamente
#  TAB 2: Procesar → corta segmentos, separa voz, mezcla beat
#
#  Dependencias:
#    pip install yt-dlp streamlink curl_cffi demucs
#    ffmpeg debe estar en PATH (viene con Python en Windows si
#    instalas imageio-ffmpeg, o descárgalo de ffmpeg.org)
# ============================================================

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json, os, sys, threading, subprocess, time, glob
from datetime import datetime
try:
    import winsound
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

# ── Auto-parche Demucs (compatibilidad torch 2.2) ──────────
def _patch_demucs():
    try:
        import demucs
        p = os.path.join(os.path.dirname(demucs.__file__), 'separate.py')
        txt = open(p, encoding='utf-8').read()
        if 'wav -= ref.mean()' in txt:
            txt = txt.replace('wav -= ref.mean()', 'wav = wav - ref.mean()')
            txt = txt.replace('wav /= ref.std()',  'wav = wav / ref.std()')
            open(p, 'w', encoding='utf-8').write(txt)
    except Exception:
        pass
_patch_demucs()

# ── Detectar herramientas disponibles ──────────────────────
def _find_cmd(module, exe=None):
    try:
        r = subprocess.run([sys.executable, '-m', module, '--version'],
                           capture_output=True, timeout=5)
        if r.returncode == 0:
            return [sys.executable, '-m', module]
    except: pass
    if exe:
        path = os.path.join(os.path.dirname(sys.executable), 'Scripts', exe)
        if os.path.exists(path):
            return [path]
    return None

STREAMLINK = _find_cmd('streamlink', 'streamlink.exe')
YTDLP      = _find_cmd('yt_dlp',    'yt-dlp.exe') or ['yt-dlp']

def _find_ffmpeg():
    import shutil
    # 1. En PATH
    f = shutil.which('ffmpeg')
    if f: return f
    # 2. Ruta WinGet típica
    winget = os.path.expandvars(
        r'%LOCALAPPDATA%\Microsoft\WinGet\Packages'
    )
    for root, dirs, files in os.walk(winget):
        if 'ffmpeg.exe' in files:
            return os.path.join(root, 'ffmpeg.exe')
    # 3. Fallback
    return 'ffmpeg'

FFMPEG = _find_ffmpeg()

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artists.json")

# ═══════════════════════════════════════════════════════════
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("🎵 TikTok Live Recorder + Procesador")
        self.root.geometry("1010x760")
        self.root.configure(bg='#1a1a2e')
        self.root.resizable(True, True)

        # Estado Monitor
        self.artists        = []
        self.monitoring     = False
        self.recordings     = {}
        self.output_folder  = os.path.join(os.path.expanduser("~"), "TikTok_Lives")
        self.last_clipboard = ""

        # Estado Procesador
        self.proc_input_file      = tk.StringVar()
        self.proc_beat_file       = tk.StringVar()
        self.proc_output_dir      = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "TikTok_Lives"))
        self.proc_detect_segments = tk.BooleanVar(value=True)
        self.proc_separate_voz = tk.BooleanVar(value=True)
        self.proc_mix_beat     = tk.BooleanVar(value=True)
        self.proc_running      = False
        self.proc_transcribe   = tk.BooleanVar(value=True)
        self.proc_img_prompt   = tk.BooleanVar(value=True)
        self.proc_lang         = tk.StringVar(value='es — Español')
        self.proc_brand_file   = tk.StringVar()
        self.proc_brand_pos    = tk.StringVar(value='final')
        self.proc_brand_vol    = tk.IntVar(value=30)

        # Perfil de artista & metadata
        self.artist_name     = tk.StringVar(value='')
        self.artist_genre    = tk.StringVar(value='Hip-Hop / Rap')
        self.proc_song_title = tk.StringVar(value='')
        self.proc_tag_mp3    = tk.BooleanVar(value=True)
        self.proc_gen_proof  = tk.BooleanVar(value=True)
        self.proc_clean_temp = tk.BooleanVar(value=True)

        # Estado Emparejador Pro
        base_dir = os.path.join(os.path.expanduser("~"), "TikTok_Lives")
        self.match_voz_folder  = tk.StringVar(value=os.path.join(base_dir, "Voces"))
        self.match_beat_folder = tk.StringVar(value=os.path.join(base_dir, "Beats"))
        self.match_out_folder  = tk.StringVar(value=os.path.join(base_dir, "Mezclas"))
        self.mix_profile       = tk.StringVar(value="Normal")
        self.match_threshold   = tk.IntVar(value=55)
        self.match_voz_files   = []
        self.match_beat_files  = []
        self.match_pairs       = []
        self.match_running      = False
        self.mix_balance        = tk.StringVar(value='balanced')
        self.proc_gentle_master = tk.BooleanVar(value=False)
        self.has_seen_tutorial = False

        self.load_config()
        self.build_ui()
        self.root.after(500, self.check_tutorial)
        
        # Pre-cargar listas de voces y beats si las carpetas existen
        if os.path.isdir(self.match_voz_folder.get()):
            self._match_set_voz(self._match_load_folder(self.match_voz_folder.get()))
        if os.path.isdir(self.match_beat_folder.get()):
            self._match_set_beat(self._match_load_folder(self.match_beat_folder.get()))

        threading.Thread(target=self._clipboard_loop, daemon=True).start()

    # ────────────────────────────────────────────────────────
    #  UI PRINCIPAL
    # ────────────────────────────────────────────────────────
    def build_ui(self):
        # Header global
        hdr = tk.Frame(self.root, bg='#16213e', pady=10)
        hdr.pack(fill='x')
        tk.Label(hdr, text="🎵  TikTok Live Recorder + Procesador de Audio",
                 font=('Arial', 17, 'bold'), fg='#e94560', bg='#16213e').pack()
        tk.Label(hdr, text="Monitorea hasta 50 artistas · Graba lives · Separa voz · Mezcla con tu beat",
                 font=('Arial', 9), fg='#a8a8b3', bg='#16213e').pack()

        # Notebook (tabs)
        style = ttk.Style()
        style.theme_use('default')
        style.configure('TNotebook',           background='#1a1a2e', borderwidth=0)
        style.configure('TNotebook.Tab',       background='#0f3460', foreground='white',
                         padding=[14, 6], font=('Arial', 10, 'bold'))
        style.map('TNotebook.Tab',
                  background=[('selected', '#e94560')],
                  foreground=[('selected', 'white')])

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill='both', expand=True, padx=8, pady=6)

        tab1 = tk.Frame(self.nb, bg='#1a1a2e')
        tab2 = tk.Frame(self.nb, bg='#1a1a2e')
        tab3 = tk.Frame(self.nb, bg='#1a1a2e')
        self.nb.add(tab1, text='  📡 Monitor Lives  ')
        self.nb.add(tab2, text='  🎙️ Procesar Audio  ')
        self.nb.add(tab3, text='  🎯 Emparejador Pro  ')

        self._build_monitor_tab(tab1)
        self._build_processor_tab(tab2)
        self._build_matcher_tab(tab3)

        # ── Barra inferior: cierre seguro ─────────────────────
        bot = tk.Frame(self.root, bg='#0a0a1a', pady=3)
        bot.pack(fill='x', side='bottom')
        self._btn(bot, "🛑 Cerrar con seguridad", self._on_close, '#8b0000',
                  font=('Arial', 8, 'bold'), padx=10, pady=3).pack(side='right', padx=10)
        tk.Label(bot, text="Detiene todo antes de cerrar",
                 fg='#555', bg='#0a0a1a', font=('Arial', 7)).pack(side='right')

        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _btn(self, parent, text, cmd, color, **kw):
        kw.setdefault('font', ('Arial', 9, 'bold'))
        kw.setdefault('padx', 10)
        kw.setdefault('pady', 4)
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg='white', relief='flat',
                         cursor='hand2', activebackground=color, **kw)

    # ════════════════════════════════════════════════════════
    #  TAB 1 — MONITOR
    # ════════════════════════════════════════════════════════
    def _build_monitor_tab(self, parent):
        if not hasattr(self, 'auto_cut_mins'):
            self.auto_cut_mins = tk.IntVar(value=30)
            
        # Barra de controles
        ctrl = tk.Frame(parent, bg='#0f3460', pady=8)
        ctrl.pack(fill='x')

        tk.Label(ctrl, text="  @usuario o URL:", fg='#a8a8b3',
                 bg='#0f3460', font=('Arial', 10)).pack(side='left')
        self.entry = tk.Entry(ctrl, width=26, bg='#1a1a2e', fg='white',
                              insertbackground='white', relief='flat',
                              font=('Arial', 10), bd=6)
        self.entry.pack(side='left', padx=5)
        self.entry.bind('<Return>', lambda e: self.add_artist())

        self._btn(ctrl, "+ Agregar",       self.add_artist,       '#e94560').pack(side='left', padx=3)
        self.mon_btn = self._btn(ctrl, "▶ Iniciar Monitor", self.toggle_monitoring, '#533483')
        self.mon_btn.pack(side='left', padx=3)
        self._btn(ctrl, "📁 Carpeta",      self.choose_mon_folder,'#0a3d62').pack(side='left', padx=3)

        tk.Label(ctrl, text="✂️ Auto-corte:", fg='#a8a8b3', bg='#0f3460', font=('Arial', 8)).pack(side='left', padx=(10,0))
        cb_cut = ttk.Combobox(ctrl, textvariable=self.auto_cut_mins, values=[15, 30, 45, 60, 120], width=4, state='readonly')
        cb_cut.pack(side='left', padx=2)
        cb_cut.bind("<<ComboboxSelected>>", lambda e: self.save_config())
        tk.Label(ctrl, text="min", fg='#a8a8b3', bg='#0f3460', font=('Arial', 8)).pack(side='left')

        self.folder_lbl = tk.Label(ctrl, text=self.output_folder,
                                   fg='#a8a8b3', bg='#0f3460', font=('Arial', 8))
        self.folder_lbl.pack(side='left', padx=5)
        tk.Label(ctrl, text="📋 clipboard ON", fg='#00ff88',
                 bg='#0f3460', font=('Arial', 8)).pack(side='right', padx=10)

        # Cabecera tabla
        th = tk.Frame(parent, bg='#16213e', pady=4)
        th.pack(fill='x', padx=10, pady=(6, 0))
        for txt, w in [("  @Artista",20),("Estado",16),("Modo",10),("Última vez",16),("Files",6),("",5)]:
            tk.Label(th, text=txt, fg='#e94560', bg='#16213e',
                     font=('Arial', 9, 'bold'), width=w, anchor='w').pack(side='left')

        # Lista scrollable
        lf = tk.Frame(parent, bg='#1a1a2e')
        lf.pack(fill='both', expand=True, padx=10, pady=2)
        self.canvas = tk.Canvas(lf, bg='#1a1a2e', highlightthickness=0)
        sb = ttk.Scrollbar(lf, orient='vertical', command=self.canvas.yview)
        self.rows_frame = tk.Frame(self.canvas, bg='#1a1a2e')
        self.rows_frame.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0,0), window=self.rows_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        self.count_lbl = tk.Label(parent, text="0 artistas", fg='#a8a8b3',
                                   bg='#1a1a2e', font=('Arial', 9))
        self.count_lbl.pack(anchor='w', padx=12)

        # Log Monitor
        lf2 = tk.Frame(parent, bg='#1a1a2e')
        lf2.pack(fill='x', padx=10, pady=(2,8))
        tk.Label(lf2, text="Actividad:", fg='#a8a8b3', bg='#1a1a2e', font=('Arial',9)).pack(anchor='w')
        self.mon_log = tk.Text(lf2, height=4, bg='#16213e', fg='#00ff88',
                               font=('Courier',9), relief='flat', state='disabled')
        self.mon_log.pack(fill='x')

        self.refresh_list()

    # ── Artistas ────────────────────────────────────────────
    def add_artist(self, username=None):
        if username is None:
            username = self.entry.get().strip()
        if not username: return
        if 'tiktok.com/@' in username:
            username = username.split('tiktok.com/@')[1].split('/')[0].split('?')[0]
        username = username.lstrip('@').strip()
        username = username.split('/')[0].strip()  # quita /live u otras rutas accidentales
        if not username: return
        if len(self.artists) >= 50:
            self.mon_log_write("⚠️ Máximo 50 artistas"); return
        if any(a['username'].lower() == username.lower() for a in self.artists):
            self.mon_log_write(f"⚠️ @{username} ya existe"); return
        self.artists.append({'username': username, 'status': 'offline',
                              'last_live': 'Nunca', 'recording': False, 'files': 0,
                              'auto_record': True})
        self.save_config(); self.refresh_list()
        self.mon_log_write(f"✅ Agregado: @{username}")
        self.entry.delete(0, 'end')

    def remove_artist(self, username):
        if username in self.recordings:
            try: self.recordings[username].terminate()
            except: pass
            del self.recordings[username]
        self.artists = [a for a in self.artists if a['username'] != username]
        self.save_config(); self.refresh_list()
        self.mon_log_write(f"🗑️ Eliminado: @{username}")

    def toggle_auto_record(self, username):
        artist = next((a for a in self.artists if a['username'] == username), None)
        if not artist: return
        artist['auto_record'] = not artist.get('auto_record', True)
        self.save_config()
        self.refresh_list()
        modo = "AUTO 🤖 (graba solo)" if artist['auto_record'] else "MANUAL 👆 (vos decidís)"
        self.mon_log_write(f"🔄 @{username} → modo {modo}")

    def manual_record(self, username):
        """Inicia grabación manual de un artista que ya está en live."""
        artist = next((a for a in self.artists if a['username'] == username), None)
        if not artist or artist.get('recording'): return
        threading.Thread(target=self._start_recording, args=(artist,), daemon=True).start()

    def _start_recording(self, artist):
        """Arranca el proceso de grabación (usado tanto por auto como manual)."""
        username = artist['username']
        url = f"https://www.tiktok.com/@{username}/live"
        os.makedirs(self.output_folder, exist_ok=True)
        ts  = datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            if STREAMLINK:
                out = os.path.join(self.output_folder, f"{username}_{ts}.ts")
                cmd = STREAMLINK + ['--retry-max', '0', '--retry-open', '1',
                                    '-o', out, url, 'audio_only,worst']
            else:
                out = os.path.join(self.output_folder, f"{username}_{ts}.mp3")
                cmd = YTDLP + ['--no-warnings', '-x', '--audio-format', 'mp3',
                                '--audio-quality', '0', '-o', out, '--live-from-start', url]

            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(6)
            if p.poll() is None:
                artist['status']    = 'recording'
                artist['recording'] = True
                artist['last_live'] = datetime.now().strftime('%d/%m %H:%M')
                artist['files']     = artist.get('files', 0) + 1
                self.recordings[username] = p
                self.mon_log_write(f"🔴 GRABANDO LIVE: @{username}")
                self.save_config()
                if STREAMLINK and out.endswith('.ts'):
                    threading.Thread(target=self._convert_ts,
                                     args=(p, out, username), daemon=True).start()
            else:
                artist['status']    = 'offline'
                artist['recording'] = False
            self.root.after(0, self.refresh_list)
        except FileNotFoundError:
            self.mon_log_write("❌ streamlink/yt-dlp no encontrado — ejecuta instalar.bat")

    def _play_alarm(self):
        """Alarma sonora al detectar un live (no bloquea la UI)."""
        def _beep():
            if _HAS_WINSOUND:
                for _ in range(3):
                    winsound.Beep(1000, 200)
                    time.sleep(0.1)
            else:
                self.root.bell()
        threading.Thread(target=_beep, daemon=True).start()

    def stop_recording(self, username):
        """Corta la grabación actual, guarda el archivo y reanuda si sigue en live."""
        proc = self.recordings.get(username)
        artist = next((a for a in self.artists if a['username'] == username), None)
        if not proc:
            return

        # Actualizar estado visualmente
        if artist:
            artist['status']    = 'monitoring'
            artist['recording'] = False
        self.root.after(0, self.refresh_list)

        # Terminar el proceso — _convert_ts ya está esperando proc.wait() y guardará el .mp3
        try:
            proc.terminate()
        except Exception:
            pass
        if username in self.recordings:
            del self.recordings[username]

        self.mon_log_write(f"⏹ Grabación cortada — guardando segmento de @{username}...")

        # Reanudar monitoreo en 5 seg: si sigue en live, arranca nueva grabación
        if artist and self.monitoring:
            threading.Thread(target=self._recheck_after_cut,
                             args=(artist,), daemon=True).start()

    def _recheck_after_cut(self, artist):
        """Espera que el archivo se convierta y vuelve a chequear si el live sigue activo."""
        time.sleep(5)
        if self.monitoring:
            self.check_artist(artist)

    def refresh_list(self):
        for w in self.rows_frame.winfo_children(): w.destroy()
        SC = {'offline':'#555','monitoring':'#f5a623','live':'#00dd66','recording':'#e94560'}
        SI = {'offline':'⚫','monitoring':'🟡','live':'🟢','recording':'🔴'}

        for i, a in enumerate(self.artists):
            status = a.get('status', 'offline')
            is_live      = status == 'live'
            is_recording = a.get('recording', False)
            auto         = a.get('auto_record', True)

            # Fila verde brillante si está en live esperando grabar manual
            if is_live and not is_recording:
                bg = '#0d3320'
            elif is_recording:
                bg = '#2a0d1e'
            else:
                bg = '#1e1e3a' if i % 2 == 0 else '#16213e'

            row = tk.Frame(self.rows_frame, bg=bg, pady=4)
            row.pack(fill='x', pady=1)

            col  = SC.get(status, '#555')
            icon = SI.get(status, '⚫')

            tk.Label(row, text=f"  @{a['username']}", fg='white', bg=bg, width=20, anchor='w',
                     font=('Arial', 10)).pack(side='left')
            tk.Label(row, text=f"{icon} {status.upper()}", fg=col, bg=bg, width=16,
                     anchor='w', font=('Arial', 9, 'bold')).pack(side='left')

            # Toggle AUTO / MANUAL
            modo_color = '#1a6b3a' if auto else '#4a3a00'
            modo_text  = '🤖 AUTO' if auto else '👆 MANUAL'
            tk.Button(row, text=modo_text, font=('Arial', 7, 'bold'),
                      command=lambda u=a['username']: self.toggle_auto_record(u),
                      bg=modo_color, fg='white', relief='flat', padx=4,
                      cursor='hand2', width=8).pack(side='left', padx=2)

            tk.Label(row, text=a.get('last_live', 'Nunca'), fg='#a8a8b3', bg=bg,
                     width=16, anchor='w', font=('Arial', 9)).pack(side='left')
            tk.Label(row, text=str(a.get('files', 0)), fg='#a8a8b3', bg=bg,
                     width=6, anchor='w').pack(side='left')

            # Botón de acción principal
            if is_recording:
                tk.Button(row, text="⏹ Cortar", font=('Arial', 8, 'bold'),
                          command=lambda u=a['username']: self.stop_recording(u),
                          bg='#f5a623', fg='#1a1a2e', relief='flat', padx=6,
                          cursor='hand2').pack(side='left', padx=2)
            elif not auto:
                # En modo manual: siempre mostrar botón para forzar grabar ahora
                tk.Button(row, text="⏺ Grabar", font=('Arial', 8, 'bold'),
                          command=lambda u=a['username']: self.manual_record(u),
                          bg='#00dd66', fg='#0a1a0a', relief='flat', padx=6,
                          cursor='hand2').pack(side='left', padx=2)
            else:
                tk.Label(row, text="", bg=bg, width=9).pack(side='left', padx=2)

            tk.Button(row, text="✕", command=lambda u=a['username']: self.remove_artist(u),
                      bg='#e94560', fg='white', relief='flat', padx=5, font=('Arial', 9),
                      cursor='hand2').pack(side='left', padx=4)

        en_live    = sum(1 for a in self.artists if a.get('status') in ('live', 'recording'))
        grabando   = sum(1 for a in self.artists if a.get('recording'))
        esperando  = en_live - grabando
        resumen = f"{len(self.artists)} artistas"
        if en_live:
            resumen += f"  |  🟢 {en_live} en LIVE"
        if grabando:
            resumen += f"  |  🔴 {grabando} grabando"
        if esperando:
            resumen += f"  |  ⏳ {esperando} esperando grabar"
        self.count_lbl.config(text=resumen)

    # ── Monitoreo ───────────────────────────────────────────
    def toggle_monitoring(self):
        self.monitoring = not self.monitoring
        if self.monitoring:
            self.mon_btn.config(text="⏹ Detener Monitor", bg='#e94560')
            self.mon_log_write("🚀 Monitoreo iniciado — revisando cada 60 seg")
            threading.Thread(target=self.monitor_loop, daemon=True).start()
        else:
            self.mon_btn.config(text="▶ Iniciar Monitor", bg='#533483')
            self.mon_log_write("⏹ Monitoreo detenido")

    def monitor_loop(self):
        while self.monitoring:
            for artist in list(self.artists):
                if not self.monitoring: break
                self.check_artist(artist)
            for _ in range(60):
                if not self.monitoring: break
                time.sleep(1)

    def check_artist(self, artist):
        username = artist['username']
        url      = f"https://www.tiktok.com/@{username}/live"
        proc     = self.recordings.get(username)

        # Ya está grabando → actualizar estado y salir
        if proc and proc.poll() is None:
            artist['status'] = 'recording'; artist['recording'] = True
            self.root.after(0, self.refresh_list); return

        # El proceso terminó → live terminó
        if proc and proc.poll() is not None:
            artist['status'] = 'offline'; artist['recording'] = False
            del self.recordings[username]
            self.mon_log_write(f"✅ Live terminado: @{username}")

        artist['status'] = 'monitoring'
        self.root.after(0, self.refresh_list)

        # ── Detectar si hay live activo usando streamlink ──────
        # Intentamos conectar y esperamos 6 seg: si el proceso sigue vivo = hay live
        os.makedirs(self.output_folder, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')

        try:
            if STREAMLINK:
                out_probe = os.path.join(self.output_folder, f"{username}_{ts}.ts")
                cmd_probe  = STREAMLINK + ['--retry-max', '0', '--retry-open', '1',
                                           '-o', out_probe, url, 'best']
            else:
                out_probe = os.path.join(self.output_folder, f"{username}_{ts}.mp3")
                cmd_probe  = YTDLP + ['--no-warnings', '-x', '--audio-format', 'mp3',
                                       '--audio-quality', '0', '-o', out_probe,
                                       '--live-from-start', url]

            p = subprocess.Popen(cmd_probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(6)

            if p.poll() is None:
                # ── Live detectado ──────────────────────────────
                self._play_alarm()
                self.mon_log_write(f"🟢 LIVE detectado: @{username}")

                if artist.get('auto_record', True):
                    # AUTO: arranca grabación inmediatamente
                    artist['status']    = 'recording'
                    artist['recording'] = True
                    artist['last_live'] = datetime.now().strftime('%d/%m %H:%M')
                    artist['files']     = artist.get('files', 0) + 1
                    self.recordings[username] = p
                    self.mon_log_write(f"🔴 GRABANDO LIVE: @{username}")
                    self.save_config()
                    if STREAMLINK and out_probe.endswith('.ts'):
                        threading.Thread(target=self._convert_ts,
                                         args=(p, out_probe, username), daemon=True).start()
                else:
                    # MANUAL: detener el probe, marcar como live, esperar que el usuario grabe
                    try: p.terminate()
                    except: pass
                    # Borrar el .ts vacío del probe si existe
                    if os.path.exists(out_probe) and os.path.getsize(out_probe) == 0:
                        try: os.remove(out_probe)
                        except: pass
                    artist['status']    = 'live'
                    artist['recording'] = False
                    artist['last_live'] = datetime.now().strftime('%d/%m %H:%M')
                    self.mon_log_write(f"🟢 @{username} en LIVE — esperando que presiones ⏺ Grabar")
            else:
                artist['status']    = 'offline'
                artist['recording'] = False

            self.root.after(0, self.refresh_list)

        except FileNotFoundError:
            self.mon_log_write("❌ streamlink/yt-dlp no encontrado — ejecuta instalar.bat")
            self.monitoring = False
            self.root.after(0, lambda: self.mon_btn.config(text="▶ Iniciar Monitor", bg='#533483'))

    def _convert_ts(self, proc, ts_path, username):
        timeout_reached = False
        try:
            timeout_sec = self.auto_cut_mins.get() * 60
            proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            timeout_reached = True
            # Cortar de forma segura, esto dispara el _recheck_after_cut y arranca otro
            self.root.after(0, lambda: self.stop_recording(username))
            proc.wait() # Esperar a que muera para procesar
            
        if not os.path.exists(ts_path) or os.path.getsize(ts_path) == 0: return
        mp3 = ts_path.replace('.ts', '.mp3')
        self.mon_log_write(f"🔄 Convirtiendo a MP3: @{username}...")
        r = subprocess.run([FFMPEG,'-i',ts_path,'-vn','-c:a','mp3','-q:a','0',mp3,'-y'],
                           capture_output=True)
        if r.returncode == 0:
            os.remove(ts_path)
            self.mon_log_write(f"✅ MP3 listo: {os.path.basename(mp3)}")
        else:
            self.mon_log_write(f"⚠️ Conversión falló, guardado como .ts: @{username}")
            
        # Si NO hubo timeout (se cayó la conexión o terminó el live normal),
        # disparamos el re-check en 5s para detectar falsas caídas rápido
        if not timeout_reached:
            artist = next((a for a in self.artists if a['username'] == username), None)
            if artist and self.monitoring and artist.get('auto_record'):
                threading.Thread(target=self._recheck_after_cut, args=(artist,), daemon=True).start()

    def choose_mon_folder(self):
        f = filedialog.askdirectory(title="Carpeta para lives")
        if f:
            self.output_folder = f
            self.folder_lbl.config(text=f)
            self.save_config()

    def mon_log_write(self, msg):
        def _do():
            self.mon_log.config(state='normal')
            self.mon_log.insert('end', f"[{datetime.now():%H:%M:%S}] {msg}\n")
            self.mon_log.see('end')
            self.mon_log.config(state='disabled')
        self.root.after(0, _do)

    # ════════════════════════════════════════════════════════
    #  TAB 2 — PROCESADOR DE VOZ
    # ════════════════════════════════════════════════════════
    def _build_processor_tab(self, parent):
        dnd_hint = "  (arrastrá un archivo acá)" if _HAS_DND else ""

        # ── ① Archivo de entrada ──────────────────────────────
        self._section(parent, f"① Grabación a procesar (MP3 / WAV / WMA / OGG){dnd_hint}")
        f1 = tk.Frame(parent, bg='#1a1a2e'); f1.pack(fill='x', padx=14, pady=4)
        inp_entry = tk.Entry(f1, textvariable=self.proc_input_file, width=64,
                             bg='#16213e', fg='white', insertbackground='white',
                             relief='flat', font=('Arial',9), bd=4)
        inp_entry.pack(side='left', padx=(0,6))
        self._bind_drop(inp_entry, self.proc_input_file)
        self._btn(f1, "Buscar archivo", self._browse_input, '#0a3d62').pack(side='left')
        self._btn(f1, "Mis lives grabados", self._pick_from_lives, '#533483').pack(side='left', padx=6)

        # ── ② Opciones de procesamiento ──────────────────────
        self._section(parent, "② Opciones de extracción de voz")
        f2 = tk.Frame(parent, bg='#1a1a2e'); f2.pack(fill='x', padx=14, pady=6)
        tk.Checkbutton(f2,
                       text="✂️   Detectar y cortar solo los segmentos donde rapeas / cantas",
                       variable=self.proc_detect_segments,
                       fg='white', bg='#1a1a2e', selectcolor='#16213e',
                       font=('Arial',10), activebackground='#1a1a2e',
                       activeforeground='white').pack(anchor='w', pady=2)
        tk.Checkbutton(f2,
                       text="🎤   Separar voz del fondo con Demucs IA — elimina copyright del live",
                       variable=self.proc_separate_voz,
                       fg='white', bg='#1a1a2e', selectcolor='#16213e',
                       font=('Arial',10), activebackground='#1a1a2e',
                       activeforeground='white').pack(anchor='w', pady=2)

        hint = tk.Frame(parent, bg='#16213e'); hint.pack(fill='x', padx=14, pady=(4,0))
        tk.Label(hint,
                 text="  → Los archivos de voz limpios se guardan en la carpeta de salida."
                      "  Luego arrástralos al Mix Studio (Tab 3) para mezclar con tu beat.",
                 fg='#a8a8b3', bg='#16213e', font=('Arial',9,'italic'),
                 justify='left').pack(anchor='w', padx=8, pady=6)

        # ── ③ Carpeta de salida ───────────────────────────────
        self._section(parent, "③ Carpeta de salida")
        f3 = tk.Frame(parent, bg='#1a1a2e'); f3.pack(fill='x', padx=14, pady=4)
        tk.Entry(f3, textvariable=self.proc_output_dir, width=64,
                 bg='#16213e', fg='white', insertbackground='white',
                 relief='flat', font=('Arial',9), bd=4).pack(side='left', padx=(0,6))
        self._btn(f3, "Cambiar", self._browse_output, '#0a3d62').pack(side='left')

        # ── Botón + status ────────────────────────────────────
        bf = tk.Frame(parent, bg='#1a1a2e'); bf.pack(fill='x', padx=14, pady=16)
        self.proc_btn = self._btn(bf, "▶  EXTRAER VOZ", self.start_processing, '#e94560',
                                  font=('Arial',13,'bold'), padx=28, pady=10)
        self.proc_btn.pack(side='left')
        self.proc_status_lbl = tk.Label(bf, text="", fg='#00ff88', bg='#1a1a2e',
                                         font=('Arial',10,'bold'))
        self.proc_status_lbl.pack(side='left', padx=16)

        self.proc_bar = ttk.Progressbar(parent, mode='indeterminate', length=500)
        self.proc_bar.pack(padx=14, pady=(0,8))

        # ── Log ───────────────────────────────────────────────
        lf = tk.Frame(parent, bg='#1a1a2e'); lf.pack(fill='both', expand=True, padx=14, pady=(0,12))
        tk.Label(lf, text="Proceso:", fg='#a8a8b3', bg='#1a1a2e', font=('Arial',9)).pack(anchor='w')
        self.proc_log = tk.Text(lf, height=10, bg='#16213e', fg='#00ff88',
                                font=('Courier',9), relief='flat', state='disabled')
        sb2 = ttk.Scrollbar(lf, orient='vertical', command=self.proc_log.yview)
        self.proc_log.configure(yscrollcommand=sb2.set)
        self.proc_log.pack(side='left', fill='both', expand=True)
        sb2.pack(side='right', fill='y')

    # ════════════════════════════════════════════════════════
    #  TAB 3 — MIX STUDIO & EMPAREJADOR PRO
    # ════════════════════════════════════════════════════════
    def _build_matcher_tab(self, parent):

        # ╔══════════════════════════════════════════════════╗
        #  PANEL DE CONFIGURACIÓN DE MEZCLA
        # ╚══════════════════════════════════════════════════╝
        cfg = tk.LabelFrame(parent, text="  ⚙️  Configuración de mezcla  ",
                            bg='#0f3460', fg='#e94560',
                            font=('Arial',9,'bold'), bd=1, relief='groove')
        cfg.pack(fill='x', padx=10, pady=(8,2))

        # Fila 1: Balance + Gentle + Transcripción
        row1 = tk.Frame(cfg, bg='#0f3460'); row1.pack(fill='x', padx=8, pady=(5,2))
        tk.Label(row1, text="⚖️ Balance:", fg='#a8a8b3', bg='#0f3460',
                 font=('Arial',9)).pack(side='left')
        for _v, _l in [('voz','🎤 Voz'), ('balanced','⚖️ Balanceado'), ('beat','🎵 Beat')]:
            tk.Radiobutton(row1, text=_l, variable=self.mix_balance, value=_v,
                           fg='white', bg='#0f3460', selectcolor='#1a1a2e',
                           activebackground='#0f3460', activeforeground='white',
                           font=('Arial',9)).pack(side='left', padx=5)
        tk.Label(row1, text="   ", bg='#0f3460').pack(side='left')
        tk.Label(row1, text="🎛️ Perfil:", fg='#a8a8b3', bg='#0f3460',
                 font=('Arial',9)).pack(side='left')
        ttk.Combobox(row1, textvariable=self.mix_profile,
                     values=['Normal','PRO (Estudio)','Masterizada (Radio)'],
                     width=18, state='readonly', font=('Arial',8)
                     ).pack(side='left', padx=4)
        tk.Label(row1, text="   ", bg='#0f3460').pack(side='left')
        tk.Checkbutton(row1, text="📝 Transcribir letra",
                       variable=self.proc_transcribe,
                       fg='white', bg='#0f3460', selectcolor='#1a1a2e',
                       font=('Arial',9), activebackground='#0f3460',
                       activeforeground='white').pack(side='left', padx=4)
        tk.Checkbutton(row1, text="🖼️ Prompt imagen",
                       variable=self.proc_img_prompt,
                       fg='white', bg='#0f3460', selectcolor='#1a1a2e',
                       font=('Arial',9), activebackground='#0f3460',
                       activeforeground='white').pack(side='left', padx=4)
        # Idioma inline
        ttk.Combobox(row1, textvariable=self.proc_lang,
                     values=['es — Español','en — English','Auto-detectar'],
                     width=13, state='readonly', font=('Arial',8)
                     ).pack(side='left', padx=4)

        # Fila 2: Marca + Artista + Tags
        row2 = tk.Frame(cfg, bg='#0f3460'); row2.pack(fill='x', padx=8, pady=(2,5))
        tk.Label(row2, text="🎙️ Marca:", fg='#a8a8b3', bg='#0f3460',
                 font=('Arial',9)).pack(side='left')
        brand_e = tk.Entry(row2, textvariable=self.proc_brand_file, width=22,
                           bg='#16213e', fg='white', insertbackground='white',
                           relief='flat', font=('Arial',8), bd=3)
        brand_e.pack(side='left', padx=(2,2))
        self._bind_drop(brand_e, self.proc_brand_file)
        self._btn(row2, "📁", self._browse_brand, '#0a3d62',
                  font=('Arial',8,'bold'), padx=4, pady=2).pack(side='left')
        self._btn(row2, "✕", lambda: self.proc_brand_file.set(''), '#555',
                  font=('Arial',8,'bold'), padx=4, pady=2).pack(side='left', padx=2)
        self.brand_vol_lbl2 = tk.Label(row2, text="30%", fg='white', bg='#0f3460',
                                        font=('Arial',8,'bold'), width=4)
        self.brand_vol_lbl2.pack(side='left')
        ttk.Scale(row2, from_=0, to=100, variable=self.proc_brand_vol,
                  orient='horizontal', length=70,
                  command=lambda v: self.brand_vol_lbl2.config(
                      text=f"{int(float(v))}%")).pack(side='left', padx=2)
        for _v, _l in [('inicio','⏮'),('medio','⏸'),('final','⏭')]:
            tk.Radiobutton(row2, text=_l, variable=self.proc_brand_pos, value=_v,
                           fg='white', bg='#0f3460', selectcolor='#1a1a2e',
                           activebackground='#0f3460', font=('Arial',9)
                           ).pack(side='left', padx=2)

        tk.Label(row2, text="   Artista:", fg='#a8a8b3', bg='#0f3460',
                 font=('Arial',9)).pack(side='left', padx=(8,2))
        tk.Entry(row2, textvariable=self.artist_name, width=14,
                 bg='#16213e', fg='white', insertbackground='white',
                 relief='flat', font=('Arial',8), bd=3).pack(side='left', padx=2)
        ttk.Combobox(row2, textvariable=self.artist_genre, width=12, state='readonly',
                     font=('Arial',8),
                     values=['Hip-Hop / Rap','Trap','Drill','R&B / Soul','Pop',
                             'Reggaeton','Latin Urban','Electronic','Lo-Fi','Freestyle','Otro']
                     ).pack(side='left', padx=4)
        tk.Checkbutton(row2, text="🏷️ Tags ID3",
                       variable=self.proc_tag_mp3,
                       fg='white', bg='#0f3460', selectcolor='#1a1a2e',
                       font=('Arial',9), activebackground='#0f3460',
                       activeforeground='white').pack(side='left', padx=4)
        tk.Checkbutton(row2, text="🔏 Autoría",
                       variable=self.proc_gen_proof,
                       fg='white', bg='#0f3460', selectcolor='#1a1a2e',
                       font=('Arial',9), activebackground='#0f3460',
                       activeforeground='white').pack(side='left', padx=4)
        tk.Checkbutton(row2, text="🧹 Limpiar temp",
                       variable=self.proc_clean_temp,
                       fg='#a8a8b3', bg='#0f3460', selectcolor='#1a1a2e',
                       font=('Arial',9), activebackground='#0f3460',
                       activeforeground='white').pack(side='left', padx=4)

        # ╔══════════════════════════════════════════════════╗
        #  PANELES DE CARGA  (Voces + Beats)
        # ╚══════════════════════════════════════════════════╝
        top = tk.Frame(parent, bg='#1a1a2e')
        top.pack(fill='x', padx=10, pady=(6,4))

        def _panel(master, title):
            lf = tk.LabelFrame(master, text=f" {title} ", bg='#1a1a2e', fg='#e94560',
                               font=('Arial', 9, 'bold'), bd=1, relief='groove')
            lf.pack(side='left', fill='both', expand=True, padx=4)
            return lf

        # Panel voces
        pv = _panel(top, "🎤  Voces (MP3 / WAV)")
        fvb = tk.Frame(pv, bg='#1a1a2e'); fvb.pack(fill='x', padx=6, pady=4)
        tk.Entry(fvb, textvariable=self.match_voz_folder, width=30,
                 bg='#16213e', fg='white', insertbackground='white',
                 relief='flat', font=('Arial',8), bd=3).pack(side='left', padx=(0,3))
        self._btn(fvb, "📁 Carpeta", self._match_browse_voz, '#0a3d62',
                  font=('Arial',8,'bold'), padx=6, pady=2).pack(side='left', padx=2)
        self._btn(fvb, "+ Archivos", self._match_add_voz, '#533483',
                  font=('Arial',8,'bold'), padx=6, pady=2).pack(side='left', padx=2)
        self._btn(fvb, "− Quitar", lambda: self._match_remove('voz'), '#8b2252',
                  font=('Arial',8,'bold'), padx=6, pady=2).pack(side='left', padx=2)
        self._btn(fvb, "✕ Limpiar", lambda: self._match_clear('voz'), '#555',
                  font=('Arial',8,'bold'), padx=6, pady=2).pack(side='left', padx=2)
        self.match_voz_lb = tk.Listbox(pv, bg='#16213e', fg='#a8a8b3',
                                        font=('Courier',8), height=7,
                                        selectbackground='#e94560', selectmode='extended')
        self.match_voz_lb.pack(fill='both', expand=True, padx=6, pady=(0,2))
        self.match_voz_lb.bind('<Delete>', lambda e: self._match_remove('voz'))
        self.match_voz_lb.bind('<Double-1>', lambda e: self._open_audio_editor(self.match_voz_lb))
        self.match_voz_count = tk.Label(pv, text="0 archivos", fg='#a8a8b3',
                                         bg='#1a1a2e', font=('Arial',8))
        self.match_voz_count.pack(anchor='w', padx=6, pady=(0,4))

        # Panel beats
        pb = _panel(top, "🥁  Beats / Instrumentales")
        fbb = tk.Frame(pb, bg='#1a1a2e'); fbb.pack(fill='x', padx=6, pady=4)
        tk.Entry(fbb, textvariable=self.match_beat_folder, width=30,
                 bg='#16213e', fg='white', insertbackground='white',
                 relief='flat', font=('Arial',8), bd=3).pack(side='left', padx=(0,3))
        self._btn(fbb, "📁 Carpeta", self._match_browse_beat, '#0a3d62',
                  font=('Arial',8,'bold'), padx=6, pady=2).pack(side='left', padx=2)
        self._btn(fbb, "+ Archivos", self._match_add_beat, '#533483',
                  font=('Arial',8,'bold'), padx=6, pady=2).pack(side='left', padx=2)
        self._btn(fbb, "− Quitar", lambda: self._match_remove('beat'), '#8b2252',
                  font=('Arial',8,'bold'), padx=6, pady=2).pack(side='left', padx=2)
        self._btn(fbb, "✕ Limpiar", lambda: self._match_clear('beat'), '#555',
                  font=('Arial',8,'bold'), padx=6, pady=2).pack(side='left', padx=2)
        self.match_beat_lb = tk.Listbox(pb, bg='#16213e', fg='#a8a8b3',
                                         font=('Courier',8), height=7,
                                         selectbackground='#e94560', selectmode='extended')
        self.match_beat_lb.pack(fill='both', expand=True, padx=6, pady=(0,2))
        self.match_beat_lb.bind('<Delete>', lambda e: self._match_remove('beat'))
        self.match_beat_count = tk.Label(pb, text="0 archivos", fg='#a8a8b3',
                                          bg='#1a1a2e', font=('Arial',8))
        self.match_beat_count.pack(anchor='w', padx=6, pady=(0,4))

        # ── Barra de control ──────────────────────────────────
        ctrl = tk.Frame(parent, bg='#0f3460', pady=6)
        ctrl.pack(fill='x')

        self.match_btn = self._btn(ctrl, "🔍 Analizar compatibilidad",
                                    self.start_match_analysis, '#533483',
                                    font=('Arial',10,'bold'), padx=14, pady=6)
        self.match_btn.pack(side='left', padx=10)

        tk.Label(ctrl, text="Umbral mínimo:", fg='#a8a8b3', bg='#0f3460',
                 font=('Arial',9)).pack(side='left', padx=(10,2))
        self.match_thresh_lbl = tk.Label(ctrl, text="55%", fg='white',
                                          bg='#0f3460', font=('Arial',9,'bold'), width=4)
        self.match_thresh_lbl.pack(side='left')
        ttk.Scale(ctrl, from_=0, to=100, variable=self.match_threshold,
                  orient='horizontal', length=110,
                  command=lambda v: self.match_thresh_lbl.config(
                      text=f"{int(float(v))}%")).pack(side='left', padx=4)

        self.match_bar = ttk.Progressbar(ctrl, mode='determinate', length=140)
        self.match_bar.pack(side='left', padx=8)
        self.match_status = tk.Label(ctrl, text="", fg='#00ff88', bg='#0f3460',
                                      font=('Arial',9,'bold'))
        self.match_status.pack(side='left', padx=6)

        # ── Tabla de resultados ───────────────────────────────
        tk.Label(parent, text="  Resultados — ordenados por compatibilidad total:",
                 fg='#a8a8b3', bg='#1a1a2e', font=('Arial',9)).pack(anchor='w', padx=10, pady=(6,0))

        tf = tk.Frame(parent, bg='#1a1a2e')
        tf.pack(fill='both', expand=True, padx=10, pady=2)

        cols = ('voz','beat','bpm_v','bpm_b','bpm_pct','key_pct','energy_pct','total','decision')
        self.match_tree = ttk.Treeview(tf, columns=cols, show='headings',
                                        height=9, selectmode='extended')
        s = ttk.Style()
        s.configure('M.Treeview',         background='#16213e', foreground='white',
                    fieldbackground='#16213e', rowheight=22)
        s.configure('M.Treeview.Heading', background='#0f3460', foreground='#e94560',
                    font=('Arial',8,'bold'))
        s.map('M.Treeview', background=[('selected','#533483')])
        self.match_tree.configure(style='M.Treeview')

        heads = [('voz','Voz',175), ('beat','Beat',175), ('bpm_v','BPM Voz',72),
                 ('bpm_b','BPM Beat',72), ('bpm_pct','BPM %',58), ('key_pct','Tono %',58),
                 ('energy_pct','Energía %',70), ('total','TOTAL',58), ('decision','Decisión',130)]
        for col, txt, w in heads:
            self.match_tree.heading(col, text=txt,
                command=lambda c=col: self._match_sort(c))
            self.match_tree.column(col, width=w, anchor='center' if col not in ('voz','beat') else 'w')

        self.match_tree.tag_configure('excelente', background='#0a2e1a', foreground='#00ff88')
        self.match_tree.tag_configure('bueno',     background='#1a3300', foreground='#77cc33')
        self.match_tree.tag_configure('regular',   background='#332800', foreground='#f5a623')
        self.match_tree.tag_configure('no_recmd',  background='#2a0808', foreground='#e94560')

        vsb = ttk.Scrollbar(tf, orient='vertical',   command=self.match_tree.yview)
        hsb = ttk.Scrollbar(tf, orient='horizontal', command=self.match_tree.xview)
        self.match_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.match_tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        # ── Acciones de mezcla ────────────────────────────────
        act = tk.Frame(parent, bg='#0f3460', pady=6)
        act.pack(fill='x')

        # Botón principal de asignación óptima
        self._btn(act, "🎯 Mejor Asignación (sin repetidos)",
                  self.show_best_assignment, '#e94560',
                  font=('Arial',10,'bold'), padx=14, pady=6).pack(side='left', padx=6)

        tk.Label(act, text="  o mezclar:", fg='#a8a8b3', bg='#0f3460',
                 font=('Arial',9)).pack(side='left', padx=(6,0))
        self._btn(act, "🎧 Pre-escucha", lambda: self.preview_batch_mix('listen'), '#008b8b',
                  font=('Arial',9,'bold'), padx=6, pady=4).pack(side='left', padx=4)
        self._btn(act, "⚡ Top 5",   lambda: self.preview_batch_mix(5),    '#533483',
                  font=('Arial',9,'bold'), padx=6, pady=4).pack(side='left', padx=2)
        self._btn(act, "⚡ Top 10",  lambda: self.preview_batch_mix(10),   '#533483',
                  font=('Arial',9,'bold'), padx=6, pady=4).pack(side='left', padx=2)
        self._btn(act, "⚡ Seleccionados", lambda: self.preview_batch_mix(None), '#533483',
                  font=('Arial',9,'bold'), padx=6, pady=4).pack(side='left', padx=2)
        self._btn(act, "🤖 IA Letra", lambda: subprocess.run(['cmd','/c','start','https://chatgpt.com']), '#533483', font=('Arial',9,'bold'), padx=6, pady=4).pack(side='left', padx=2)
        self._btn(act, "🎨 IA Portada", lambda: subprocess.run(['cmd','/c','start','https://www.bing.com/images/create']), '#533483', font=('Arial',9,'bold'), padx=6, pady=4).pack(side='left', padx=2)
        self._btn(act, "⚡ Todos", lambda: self.preview_batch_mix('all'), '#1a6b3a',
                  font=('Arial',9,'bold'), padx=6, pady=4).pack(side='left', padx=2)

        tk.Label(act, text="  →  Salida:", fg='#a8a8b3', bg='#0f3460',
                 font=('Arial',9)).pack(side='left', padx=(16,3))
        tk.Entry(act, textvariable=self.match_out_folder, width=26,
                 bg='#16213e', fg='white', insertbackground='white',
                 relief='flat', font=('Arial',8), bd=3).pack(side='left')
        self._btn(act, "📁", self._match_browse_out, '#0a3d62',
                  font=('Arial',9,'bold'), padx=6, pady=4).pack(side='left', padx=3)

        self.match_mix_status = tk.Label(act, text="", fg='#00ff88', bg='#0f3460',
                                          font=('Arial',8,'bold'))
        self.match_mix_status.pack(side='left', padx=8)

        # ── Log del Emparejador ──
        mlog_f = tk.Frame(parent, bg='#1a1a2e')
        mlog_f.pack(fill='both', expand=True, padx=10, pady=(2,6))
        tk.Label(mlog_f, text="Log:", fg='#a8a8b3', bg='#1a1a2e',
                 font=('Arial',8)).pack(anchor='w')
        self.matcher_log = tk.Text(mlog_f, height=4, bg='#16213e', fg='#00ff88',
                                    font=('Courier',8), relief='flat', state='disabled')
        mlsb = ttk.Scrollbar(mlog_f, orient='vertical', command=self.matcher_log.yview)
        self.matcher_log.configure(yscrollcommand=mlsb.set)
        self.matcher_log.pack(side='left', fill='both', expand=True)
        mlsb.pack(side='right', fill='y')

        # Drag & drop en listboxes
        if _HAS_DND:
            self._bind_folder_drop(self.match_voz_lb, 'voz')
            self._bind_folder_drop(self.match_beat_lb, 'beat')

    def _section(self, parent, text):
        f = tk.Frame(parent, bg='#0f3460', pady=4)
        f.pack(fill='x', padx=0, pady=(8,0))
        tk.Label(f, text=f"  {text}", fg='white', bg='#0f3460',
                 font=('Arial',9,'bold')).pack(anchor='w')

    # ── Navegadores de archivo ───────────────────────────────
    def _browse_input(self):
        f = filedialog.askopenfilename(
            title="Selecciona tu grabación",
            filetypes=[("Audio","*.mp3 *.wav *.wma *.m4a *.ogg *.ts"),("Todos","*.*")])
        if f: self.proc_input_file.set(f)

    def _browse_beat(self):
        f = filedialog.askopenfilename(
            title="Selecciona tu beat/instrumental",
            filetypes=[("Audio","*.mp3 *.wav *.ogg"),("Todos","*.*")])
        if f: self.proc_beat_file.set(f)

    def _browse_output(self):
        d = filedialog.askdirectory(title="Carpeta de salida")
        if d: self.proc_output_dir.set(d)

    def _pick_from_lives(self):
        """Abre la carpeta de lives grabados para seleccionar uno"""
        folder = self.output_folder
        if not os.path.exists(folder):
            messagebox.showinfo("Vacío", "Aún no hay lives grabados en la carpeta.")
            return
        files = glob.glob(os.path.join(folder, "*.mp3")) + \
                glob.glob(os.path.join(folder, "*.wav"))
        if not files:
            messagebox.showinfo("Vacío", f"No hay archivos en {folder}")
            return
        win = tk.Toplevel(self.root)
        win.title("Elige un live grabado")
        win.geometry("600x300")
        win.configure(bg='#1a1a2e')
        lb = tk.Listbox(win, bg='#16213e', fg='white', font=('Arial',9),
                        selectbackground='#e94560')
        lb.pack(fill='both', expand=True, padx=10, pady=10)
        for f in sorted(files, key=os.path.getmtime, reverse=True):
            lb.insert('end', os.path.basename(f))
        def select():
            sel = lb.curselection()
            if sel:
                self.proc_input_file.set(
                    os.path.join(folder, lb.get(sel[0])))
                win.destroy()
        self._btn(win, "Seleccionar", select, '#e94560').pack(pady=5)

    def _pick_from_desktop(self):
        """Abre ventana con los beats del escritorio del usuario"""
        desktop_paths = [
            r"X:\Desktop\instrumentales ezzien 11-04",
            r"X:\Desktop\instrumentales para ezzien 08-04",
            os.path.join(os.path.expanduser("~"), "Desktop"),
        ]
        files = []
        for p in desktop_paths:
            if os.path.exists(p):
                files += glob.glob(os.path.join(p, "*.wav")) + \
                         glob.glob(os.path.join(p, "*.mp3"))
        if not files:
            f = filedialog.askdirectory(title="¿Dónde están tus instrumentales?")
            if f:
                files = glob.glob(os.path.join(f,"*.wav")) + \
                        glob.glob(os.path.join(f,"*.mp3"))
        if not files:
            messagebox.showinfo("Vacío","No se encontraron beats."); return

        win = tk.Toplevel(self.root)
        win.title("Elige tu instrumental")
        win.geometry("650x380")
        win.configure(bg='#1a1a2e')

        # Búsqueda rápida
        sf = tk.Frame(win, bg='#1a1a2e'); sf.pack(fill='x', padx=10, pady=5)
        tk.Label(sf, text="Buscar:", fg='white', bg='#1a1a2e').pack(side='left')
        search_var = tk.StringVar()
        tk.Entry(sf, textvariable=search_var, bg='#16213e', fg='white',
                 insertbackground='white', relief='flat', bd=4, width=30).pack(side='left', padx=5)

        lb = tk.Listbox(win, bg='#16213e', fg='white', font=('Arial',9),
                        selectbackground='#e94560')
        lb.pack(fill='both', expand=True, padx=10)

        all_names = sorted([os.path.basename(f) for f in files])
        for n in all_names: lb.insert('end', n)

        def filter_list(*_):
            q = search_var.get().lower()
            lb.delete(0, 'end')
            for n in all_names:
                if q in n.lower(): lb.insert('end', n)
        search_var.trace('w', filter_list)

        def select():
            sel = lb.curselection()
            if sel:
                name = lb.get(sel[0])
                match = [f for f in files if os.path.basename(f) == name]
                if match:
                    self.proc_beat_file.set(match[0])
                win.destroy()
        self._btn(win, "Seleccionar beat", select, '#e94560').pack(pady=8)

    # ── PROCESAMIENTO PRINCIPAL ──────────────────────────────
    def start_processing(self):
        if self.proc_running:
            messagebox.showwarning("Ocupado","Ya hay un proceso en curso."); return

        input_file = self.proc_input_file.get().strip()
        if not input_file or not os.path.exists(input_file):
            messagebox.showerror("Error","Seleccioná un archivo de audio válido."); return

        out_dir = self.proc_output_dir.get().strip() or self.output_folder
        os.makedirs(out_dir, exist_ok=True)

        self.proc_running = True
        self.proc_btn.config(state='disabled', bg='#555')
        self.proc_bar.start(12)
        self.proc_status_lbl.config(text="⏳ Extrayendo voz...")
        self.proc_log_write("─" * 50)
        self.proc_log_write(f"📂 {os.path.basename(input_file)}")

        threading.Thread(
            target=self._voice_extract_thread,
            args=(input_file, out_dir),
            daemon=True
        ).start()

    def _voice_extract_thread(self, input_file, out_dir):
        """Pipeline Tab 2: solo extracción/limpieza de voz, sin mezcla."""
        try:
            base = os.path.splitext(os.path.basename(input_file))[0]
            ts   = datetime.now().strftime('%Y%m%d_%H%M%S')

            # Paso 1: Convertir a WAV
            self.proc_log_write("🔄 Paso 1/3: Preparando audio...")
            wav_raw = os.path.join(out_dir, f"{base}_raw.wav")
            r = subprocess.run([
                FFMPEG, '-i', input_file,
                '-ar', '44100', '-ac', '2', wav_raw, '-y'
            ], capture_output=True)
            if r.returncode != 0:
                self.proc_log_write("❌ Error en conversión de audio"); return

            # Paso 2: Detectar segmentos
            if self.proc_detect_segments.get():
                self.proc_log_write("🔍 Paso 2/3: Detectando segmentos de voz/rap...")
                segments = self._detect_segments(wav_raw, out_dir, base)
                self.proc_log_write(f"   → {len(segments)} segmento(s)")
                if not segments:
                    segments = [wav_raw]
            else:
                self.proc_log_write("⏭️ Paso 2/3: Sin detección — archivo completo")
                segments = [wav_raw]

            session_dir = os.path.join(out_dir, f"{base}_{ts}")
            os.makedirs(session_dir, exist_ok=True)

            # Paso 3: Separar voz (Demucs) o limpiar
            if self.proc_separate_voz.get():
                self.proc_log_write("🎤 Paso 3/3: Separando voz (Demucs htdemucs_ft)...")
                _cache = os.path.join(os.path.expanduser("~"), ".cache", "torch", "hub", "checkpoints")
                if not (os.path.isdir(_cache) and any(
                        f.startswith("htdemucs_ft") for f in os.listdir(_cache))):
                    self.proc_log_write("   ⏬ Primera vez: descargando modelo IA (~200MB)...")
                for i, seg in enumerate(segments):
                    label = f"seg{i+1:03d}"
                    self.proc_log_write(f"   ⏳ Procesando {label} ({i+1}/{len(segments)})...")
                    vf = self._run_demucs(seg, session_dir)
                    if vf:
                        no_voc = vf.replace('vocals.wav', 'no_vocals.wav')
                        if os.path.exists(no_voc): os.remove(no_voc)
                        vf_clean = os.path.join(session_dir, f"{label}_voz_limpia.wav")
                        subprocess.run([
                            FFMPEG, '-i', vf, '-af',
                            ('highpass=f=100,lowpass=f=9000,'
                             'anlmdn=s=5:p=0.002:r=0.002,'
                             'equalizer=f=2500:width_type=o:width=2:g=3,'
                             'equalizer=f=5000:width_type=o:width=2:g=2,'
                             'compand=attacks=0:points=-80/-80|-45/-45|-27/-25|-15/-10|-5/-3|0/0|5/0,'
                             'loudnorm'),
                            '-ar', '44100', '-ac', '1', vf_clean, '-y'
                        ], capture_output=True)
                        result = vf_clean if os.path.exists(vf_clean) else vf
                        self.proc_log_write(f"   ✅ {label}_voz_limpia.wav listo")
                        self._analyze_and_prompt(result, session_dir, label, ts)
                    else:
                        self.proc_log_write(f"   ⚠️ {label}: Demucs falló — usando audio sin separar")
            else:
                self.proc_log_write("🔧 Paso 3/3: Limpiando audio (sin separación IA)...")
                for i, seg in enumerate(segments):
                    label = f"seg{i+1:03d}"
                    seg_clean = os.path.join(session_dir, f"{label}_voz_limpia.wav")
                    subprocess.run([
                        FFMPEG, '-i', seg, '-af',
                        'highpass=f=100,lowpass=f=9000,anlmdn=s=5:p=0.002:r=0.002,loudnorm',
                        '-ar', '44100', '-ac', '1', seg_clean, '-y'
                    ], capture_output=True)
                    self.proc_log_write(f"   ✅ {label}_voz_limpia.wav")

            # Eliminar WAV raw
            try: os.remove(wav_raw)
            except: pass

            self.proc_log_write("─" * 46)
            self.proc_log_write(f"✅ Voz(es) listas en: {session_dir}")
            self.proc_log_write("→ Abrí el Mix Studio (Tab 3) y arrastrá los archivos.")
            self.root.after(0, lambda: self.proc_status_lbl.config(text="✅ Voz lista → Tab 3"))

        except Exception as e:
            self.proc_log_write(f"❌ Error: {e}")
            self.root.after(0, lambda: self.proc_status_lbl.config(text="❌ Error"))
        finally:
            self.proc_running = False
            self.root.after(0, self.proc_bar.stop)
            self.root.after(0, lambda: self.proc_btn.config(state='normal', bg='#e94560'))

    def start_quick_mix(self):
        """Mezcla directa: toma el audio tal cual, sin ningún procesamiento previo."""
        if self.proc_running:
            messagebox.showwarning("Ocupado", "Ya hay un proceso en curso."); return

        input_file = self.proc_input_file.get().strip()
        if not input_file or not os.path.exists(input_file):
            messagebox.showerror("Error", "Selecciona el archivo de voz a mezclar."); return

        beat_file = self.proc_beat_file.get().strip()
        if not beat_file or not os.path.exists(beat_file):
            messagebox.showerror("Error", "Selecciona el beat/instrumental."); return

        out_dir = self.proc_output_dir.get().strip() or self.output_folder
        os.makedirs(out_dir, exist_ok=True)

        self.proc_running = True
        self.proc_btn.config(state='disabled', bg='#555')
        self.mix_btn.config(state='disabled', bg='#555')
        self.proc_bar.start(12)
        self.proc_status_lbl.config(text="⏳ Mezclando...")
        self.proc_log_write("─" * 50)
        self.proc_log_write(f"⚡ MEZCLA DIRECTA: {os.path.basename(input_file)}")
        self.proc_log_write(f"   + Beat: {os.path.basename(beat_file)}")

        threading.Thread(target=self._quick_mix_thread, args=(input_file, beat_file, out_dir), daemon=True).start()

    def _quick_mix_thread(self, input_file, beat_file, out_dir):
        try:
            base    = os.path.splitext(os.path.basename(input_file))[0]
            ts      = datetime.now().strftime('%Y%m%d_%H%M%S')
            out_mp3 = os.path.join(out_dir, f"{base}_MEZCLA_{ts}.mp3")

            self.proc_log_write("🎵 Mezclando voz con beat...")
            self._mix_with_beat(input_file, beat_file, out_mp3)

            if os.path.exists(out_mp3):
                # Firma de audio
                brand_f = self.proc_brand_file.get().strip()
                if brand_f and os.path.exists(brand_f):
                    self.proc_log_write(f"🎙️ Aplicando firma de audio ({self.proc_brand_pos.get()})...")
                    branded = os.path.join(out_dir, f"{base}_BRANDED_{ts}.mp3")
                    self._add_brand_to_file(out_mp3, branded)

                # Transcripción
                if self.proc_transcribe.get():
                    self.proc_log_write("📝 Transcribiendo voz...")
                    result = self._transcribe_audio(input_file, out_dir, base, ts)
                    if result and self.proc_img_prompt.get():
                        lyrics_text, bpm_val, key_val = result
                        self._generate_image_prompt(lyrics_text, bpm_val, key_val,
                                                    out_dir, base, ts)

                self.proc_log_write(f"✅ Listo: {os.path.basename(out_mp3)}")
                self.proc_log_write(f"📁 Guardado en: {out_dir}")
                self.root.after(0, lambda: self.proc_status_lbl.config(text="✅ ¡Mezcla lista!"))
            else:
                self.proc_log_write("❌ Error al mezclar — verificá que FFmpeg esté instalado")
                self.root.after(0, lambda: self.proc_status_lbl.config(text="❌ Error"))
        except Exception as e:
            self.proc_log_write(f"❌ Error: {e}")
            self.root.after(0, lambda: self.proc_status_lbl.config(text="❌ Error"))
        finally:
            self.proc_running = False
            self.root.after(0, self.proc_bar.stop)
            self.root.after(0, lambda: self.proc_btn.config(state='normal', bg='#e94560'))
            self.root.after(0, lambda: self.mix_btn.config(state='normal', bg='#1a6b3a'))

    def _process_pipeline(self, input_file, beat_file, out_dir):
        try:
            base = os.path.splitext(os.path.basename(input_file))[0]
            ts   = datetime.now().strftime('%Y%m%d_%H%M%S')

            # ── PASO 1: Convertir a WAV sin filtros (Demucs necesita audio natural) ──
            self.proc_log_write("🔄 Paso 1/4: Preparando audio...")
            wav_raw = os.path.join(out_dir, f"{base}_raw.wav")
            r = subprocess.run([
                FFMPEG, '-i', input_file,
                '-ar', '44100', '-ac', '2', wav_raw, '-y'
            ], capture_output=True)
            if r.returncode != 0:
                self.proc_log_write("❌ Error en conversión de audio"); return

            # ── PASO 2: Detectar segmentos activos ──────────
            if self.proc_detect_segments.get():
                self.proc_log_write("🔍 Paso 2/4: Detectando segmentos de rap/canto...")
                segments = self._detect_segments(wav_raw, out_dir, base)
                self.proc_log_write(f"   → {len(segments)} segmento(s) detectado(s)")
                if not segments:
                    self.proc_log_write("⚠️ No se detectaron segmentos. Usando el archivo completo.")
                    segments = [wav_raw]
            else:
                self.proc_log_write("⏭️ Paso 2/4: Detección omitida — procesando archivo completo")
                segments = [wav_raw]

            # Carpeta de sesión: agrupa todo lo de esta grabación
            session_dir = os.path.join(out_dir, f"{base}_{ts}")
            os.makedirs(session_dir, exist_ok=True)

            # ── PASO 3: Separar voz (Demucs) + limpiar + prompt por segmento ────────
            vocals_files = []
            seg_labels   = []   # para nombrar los mp3 finales igual

            if self.proc_separate_voz.get():
                self.proc_log_write("🎤 Paso 3/4: Separando voz (Demucs htdemucs_ft)...")
                # Verificar si el modelo ya está descargado
                _cache = os.path.join(os.path.expanduser("~"), ".cache", "torch", "hub", "checkpoints")
                _model_ready = any(
                    f.startswith("htdemucs_ft") for f in os.listdir(_cache)
                ) if os.path.isdir(_cache) else False
                if _model_ready:
                    self.proc_log_write("   ✅ Modelo listo — comenzando separacion de voz...")
                else:
                    self.proc_log_write("   ⏬ Primera vez: descargando modelo IA (~200MB), aguarda un momento...")
                for i, seg in enumerate(segments):
                    label = f"seg{i+1:03d}"
                    self.proc_log_write(f"   {label} ({i+1}/{len(segments)})...")
                    vf = self._run_demucs(seg, session_dir)
                    if vf:
                        # Eliminar no_vocals.wav
                        no_voc = vf.replace('vocals.wav', 'no_vocals.wav')
                        if os.path.exists(no_voc):
                            os.remove(no_voc)

                        # Limpiar voz extraída
                        vf_clean = os.path.join(session_dir, f"{label}_voz_limpia.wav")
                        subprocess.run([
                            FFMPEG, '-i', vf,
                            '-af', ('highpass=f=100,lowpass=f=9000,'
                                    'anlmdn=s=5:p=0.002:r=0.002,'
                                    'equalizer=f=2500:width_type=o:width=2:g=3,'
                                    'equalizer=f=5000:width_type=o:width=2:g=2,'
                                    'compand=attacks=0:points=-80/-80|-45/-45|-27/-25|-15/-10|-5/-3|0/0|5/0,'
                                    'loudnorm'),
                            '-ar', '44100', '-ac', '1', vf_clean, '-y'
                        ], capture_output=True)
                        result_vf = vf_clean if os.path.exists(vf_clean) else vf
                        vocals_files.append(result_vf)
                        seg_labels.append(label)
                        self.proc_log_write(f"   ✅ {label}_voz_limpia.wav")

                        # Prompt individual para este segmento
                        self._analyze_and_prompt(result_vf, session_dir, label, ts)
                    else:
                        vocals_files.append(seg)
                        seg_labels.append(label)
                        self.proc_log_write(f"   ⚠️ Demucs falló — usando audio original")
            else:
                self.proc_log_write("🔧 Paso 3/4: Limpiando audio...")
                for i, seg in enumerate(segments):
                    label = f"seg{i+1:03d}"
                    seg_clean = os.path.join(session_dir, f"{label}_voz_limpia.wav")
                    subprocess.run([
                        FFMPEG, '-i', seg,
                        '-af', ('highpass=f=100,lowpass=f=9000,'
                                'anlmdn=s=5:p=0.002:r=0.002,'
                                'loudnorm'),
                        '-ar', '44100', '-ac', '1', seg_clean, '-y'
                    ], capture_output=True)
                    vocals_files.append(seg_clean if os.path.exists(seg_clean) else seg)
                    seg_labels.append(label)
                self.proc_log_write("⏭️ Separación de voz omitida")

            # ── PASO 4: Mezclar con beat ─────────────────────
            final_files = []   # (label, path) para la firma y transcripción
            if self.proc_mix_beat.get() and beat_file:
                self.proc_log_write("🎵 Paso 4/4: Mezclando voz con tu beat...")
                for label, vf in zip(seg_labels, vocals_files):
                    out_mp3 = os.path.join(session_dir, f"{label}_FINAL.mp3")
                    self._mix_with_beat(vf, beat_file, out_mp3)
                    self.proc_log_write(f"   ✅ {label}_FINAL.mp3")
                    final_files.append((label, vf, out_mp3))
            else:
                self.proc_log_write("⏭️ Paso 4/4: Mezcla omitida — guardando voz limpia")
                for label, vf in zip(seg_labels, vocals_files):
                    out_mp3 = os.path.join(session_dir, f"{label}_VOZ.mp3")
                    subprocess.run([FFMPEG, '-i', vf, '-b:a', '320k', out_mp3, '-y'],
                                   capture_output=True)
                    self.proc_log_write(f"   ✅ {label}_VOZ.mp3")
                    final_files.append((label, vf, out_mp3))

            # ── PASO 5: Firma de audio ────────────────────────
            brand_f = self.proc_brand_file.get().strip()
            if brand_f and os.path.exists(brand_f):
                self.proc_log_write(f"🎙️ Aplicando firma de audio ({self.proc_brand_pos.get()}, "
                                    f"{self.proc_brand_vol.get()}%)...")
                for label, vf, mp3 in final_files:
                    branded = os.path.join(session_dir, f"{label}_BRANDED.mp3")
                    if self._add_brand_to_file(mp3, branded):
                        self.proc_log_write(f"   ✅ {label}_BRANDED.mp3")

            # ── PASO 6: Transcripción voz → Letra ────────────
            all_lyrics = {}   # label → texto completo
            all_bpm    = {}
            all_key    = {}
            if self.proc_transcribe.get():
                self.proc_log_write("📝 Transcribiendo voz (Whisper IA)...")
                for label, vf, mp3 in final_files:
                    result = self._transcribe_audio(vf, session_dir, label, ts)
                    if result:
                        lyrics_text, bpm_val, key_val = result
                        all_lyrics[label] = lyrics_text
                        all_bpm[label]    = bpm_val
                        all_key[label]    = key_val
                        if self.proc_img_prompt.get():
                            self._generate_image_prompt(lyrics_text, bpm_val, key_val,
                                                        session_dir, label, ts)

            # ── PASO 7: Metadatos ID3 + Autoría + Limpieza ───
            year  = datetime.now().year
            artist = self.artist_name.get().strip() or 'Artista'
            genre  = self.artist_genre.get()

            for label, vf, mp3 in final_files:
                # Título: campo UI → desde letra → nombre de archivo
                title = self.proc_song_title.get().strip()
                if not title and label in all_lyrics:
                    suggestions = self._suggest_titles(all_lyrics[label])
                    title = suggestions[0] if suggestions else ''
                if not title:
                    title = os.path.splitext(os.path.basename(mp3))[0]

                bpm_val = all_bpm.get(label)
                key_val = all_key.get(label, '?')
                lyrics  = all_lyrics.get(label, '')

                if self.proc_tag_mp3.get():
                    self._tag_mp3(mp3, title, artist, genre, bpm_val, year, lyrics)
                    self.proc_log_write(f"   🏷️ ID3 → \"{title}\" / {artist} / {genre}")

                if self.proc_gen_proof.get():
                    proof = self._generate_proof(vf, mp3, title, artist, lyrics,
                                                 bpm_val, key_val, session_dir, ts)
                    self.proc_log_write(f"   🔏 Autoría: {os.path.basename(proof)}")

            # Limpieza de temporales
            if self.proc_clean_temp.get():
                self._clean_temp_files(session_dir)
                self.proc_log_write("🧹 Temporales eliminados")

            # Resumen final
            self._write_export_summary(session_dir, final_files, artist, genre, ts)

            self.proc_log_write("─" * 50)
            self.proc_log_write(f"🎉 ¡LISTO! Carpeta de sesión: {session_dir}")
            self.proc_log_write("📋 Revisa RESUMEN_EXPORTAR.txt para los próximos pasos")
            self.root.after(0, lambda: self.proc_status_lbl.config(text="✅ ¡Completado!"))

        except Exception as e:
            self.proc_log_write(f"❌ Error: {e}")
            self.root.after(0, lambda: self.proc_status_lbl.config(text="❌ Error"))
        finally:
            self.proc_running = False
            self.root.after(0, self.proc_bar.stop)
            self.root.after(0, lambda: self.proc_btn.config(state='normal', bg='#e94560'))

    def _detect_segments(self, input_file, out_dir, base):
        """Detecta y corta segmentos activos (donde hay rap/canto) usando ffmpeg silencedetect"""
        silence_out = subprocess.run([
            FFMPEG, '-i', input_file,
            '-af', 'silencedetect=noise=-30dB:d=1.5',
            '-f', 'null', '-'
        ], capture_output=True, text=True)

        lines = silence_out.stderr.split('\n')
        silence_starts, silence_ends = [], []
        for line in lines:
            if 'silence_start' in line:
                try: silence_starts.append(float(line.split('silence_start: ')[1].split()[0]))
                except: pass
            if 'silence_end' in line:
                try: silence_ends.append(float(line.split('silence_end: ')[1].split('|')[0].strip()))
                except: pass

        # Obtener duración total
        dur_out = subprocess.run([
            FFMPEG, '-i', input_file, '-f', 'null', '-'
        ], capture_output=True, text=True)
        total_dur = 0
        for line in dur_out.stderr.split('\n'):
            if 'Duration:' in line:
                try:
                    t = line.split('Duration:')[1].split(',')[0].strip()
                    h,m,s = t.split(':')
                    total_dur = int(h)*3600 + int(m)*60 + float(s)
                except: pass

        if not silence_starts:
            return []

        # Construir lista de segmentos activos
        active = []
        prev_end = 0.0
        for ss, se in zip(silence_starts, silence_ends):
            if ss - prev_end > 3.0:  # segmento > 3 segundos
                active.append((prev_end, ss))
            prev_end = se
        if total_dur - prev_end > 3.0:
            active.append((prev_end, total_dur))

        # Cortar segmentos
        seg_files = []
        for i, (start, end) in enumerate(active):
            seg_path = os.path.join(out_dir, f"{base}_seg{i+1:03d}.wav")
            r = subprocess.run([
                FFMPEG, '-i', input_file,
                '-ss', str(start), '-to', str(end),
                '-ar', '44100', '-ac', '1', seg_path, '-y'
            ], capture_output=True)
            if r.returncode == 0 and os.path.exists(seg_path):
                seg_files.append(seg_path)

        return seg_files

    def _run_demucs(self, audio_file, out_dir):
        """Separa voz del instrumental con Demucs. Devuelve ruta del archivo de voz."""
        try:
            env = os.environ.copy()
            env['TORCHAUDIO_BACKEND'] = 'soundfile'
            r = subprocess.run([
                sys.executable, '-m', 'demucs',
                '-n', 'htdemucs_ft',   # modelo fine-tuned, mejor calidad
                '--two-stems=vocals',
                '-o', out_dir,
                audio_file
            ], capture_output=True, text=True, timeout=600, env=env)

            if r.returncode != 0:
                self.proc_log_write(f"   ⚠️ Demucs error: {r.stderr[-200:]}")
                return None

            # Demucs guarda en: out_dir/htdemucs/NOMBRE/vocals.wav
            base = os.path.splitext(os.path.basename(audio_file))[0]
            candidates = glob.glob(os.path.join(out_dir, '**', base, 'vocals.wav'), recursive=True)
            if candidates:
                return candidates[0]
            return None
        except FileNotFoundError:
            self.proc_log_write("   ❌ Demucs no instalado — ejecuta: pip install demucs")
            return None
        except subprocess.TimeoutExpired:
            self.proc_log_write("   ⚠️ Demucs tardó demasiado — archivo muy largo")
            return None

    def _analyze_and_prompt(self, vocals_file, out_dir, base, ts):
        """Analiza la voz extraída y genera un prompt detallado para crear el beat."""
        try:
            import librosa
            import numpy as np

            self.proc_log_write("🔬 Analizando audio para generar prompt de beat...")
            y, sr = librosa.load(vocals_file, sr=None, mono=True)

            # ── BPM y ritmo ──
            tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
            bpm = float(np.atleast_1d(tempo)[0])

            # ── Tono / Key ──
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            key_idx = int(np.argmax(chroma.mean(axis=1)))
            keys    = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
            key     = keys[key_idx]

            # ── Energía y dinámica ──
            rms        = float(librosa.feature.rms(y=y).mean())
            energy_db  = float(librosa.amplitude_to_db(np.array([rms]))[0])
            zcr        = float(librosa.feature.zero_crossing_rate(y).mean())

            # ── Tempo feel ──
            if bpm < 75:    
                tempo_feel = "muy lento, introspectivo, trap lento"
                ai_tempo = "very slow, introspective, ambient trap"
            elif bpm < 95:  
                tempo_feel = "lento, relajado, lo-fi / chill trap"
                ai_tempo = "slow, chill, lo-fi hip hop, laid back"
            elif bpm < 115: 
                tempo_feel = "moderado, rap consciente / boom bap"
                ai_tempo = "mid-tempo, boom bap, conscious hip hop"
            elif bpm < 135: 
                tempo_feel = "rápido, energético, trap / drill"
                ai_tempo = "fast, energetic trap, drill"
            elif bpm < 155: 
                tempo_feel = "muy rápido, agresivo, drill / rage"
                ai_tempo = "very fast, aggressive drill, rage beat"
            else:           
                tempo_feel = "extremadamente rápido, hyperpop / speedrap"
                ai_tempo = "hyperpop, extremely fast, speed rap"

            # ── Energía feel ──
            if energy_db < -30:   
                energy_feel = "suave, susurrado, íntimo"
                ai_energy = "soft, intimate, whispered, low energy"
            elif energy_db < -20: 
                energy_feel = "moderado, conversacional"
                ai_energy = "moderate energy, conversational flow"
            elif energy_db < -12: 
                energy_feel = "potente, presencia vocal fuerte"
                ai_energy = "powerful, strong vocal presence, high energy"
            else:                 
                energy_feel = "muy potente, agresivo, en tu cara"
                ai_energy = "aggressive, very powerful, hard hitting"

            # ── Complejidad rítmica ──
            beat_strength = float(np.std(librosa.beat.beat_track(y=y, sr=sr, units='time')[1]))
            if beat_strength < 0.1:   
                rhythm_feel = "muy estable, mecánico, cuantizado"
                ai_rhythm = "quantized, mechanical rhythm, steady"
            elif beat_strength < 0.3: 
                rhythm_feel = "estable con leves variaciones naturales"
                ai_rhythm = "steady with natural groove"
            elif beat_strength < 0.6: 
                rhythm_feel = "flexible, fluido, con swag"
                ai_rhythm = "fluid rhythm, bouncy, bouncy flow"
            else:                     
                rhythm_feel = "muy libre, off-beat intencional, experimental"
                ai_rhythm = "experimental rhythm, off-beat, free tempo"

            # ── Duración ──
            duration = librosa.get_duration(y=y, sr=sr)
            mins, secs = int(duration // 60), int(duration % 60)

            # ── Generar prompt ──
            prompt = f"""
═══════════════════════════════════════════════════════
  PROMPT PARA CREAR EL BEAT — generado automáticamente
═══════════════════════════════════════════════════════

📊 DATOS TÉCNICOS DEL AUDIO:
   • BPM detectado   : {bpm:.1f} BPM
   • Tono dominante  : {key} (nota más frecuente en la voz)
   • Energía vocal   : {energy_db:.1f} dB  →  {energy_feel}
   • Duración        : {mins}:{secs:02d} min

🎵 DESCRIPCIÓN DEL ESTILO:
   • Tempo feel      : {tempo_feel}
   • Ritmo vocal     : {rhythm_feel}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PROMPT LISTO PARA SUNO / UDIO (Copiar y pegar):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"{ai_tempo}, {bpm:.0f} BPM, key of {key}, {ai_energy}, {ai_rhythm}, 
dark trap beat, heavy 808 bass, crispy hi-hats, punchy kicks.
Melodic but aggressive. Instrumental only, no vocals.
Professional mix, radio ready."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CONSEJOS PARA EL BEAT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✅ BPM exacto   : Programa el beat a {bpm:.0f} BPM para que encaje perfecto
  ✅ Tono         : Usa acordes o melodías en {key} mayor o {key} menor
  ✅ Kick & snare : Alinea el snare en el 2 y 4 del compás
  ✅ 808          : Afínalo en {key} para que no choque con tu voz
  ✅ Espacio      : Deja rango medio (800Hz-3kHz) libre para la voz
  ✅ Duración     : Haz el beat de al menos {mins+1} min para cubrir la voz

═══════════════════════════════════════════════════════
"""
            # Guardar prompt en archivo .txt
            prompt_path = os.path.join(out_dir, f"{base}_PROMPT_{ts}.txt")
            with open(prompt_path, 'w', encoding='utf-8') as f:
                f.write(prompt)

            # Mostrar en el log
            for line in prompt.strip().split('\n'):
                self.proc_log_write(line)

            self.proc_log_write(f"💾 Prompt guardado en: {os.path.basename(prompt_path)}")
            return prompt_path

        except Exception as e:
            self.proc_log_write(f"   ⚠️ Análisis falló: {e}")
            return None

    def _get_duration(self, filepath):
        """Devuelve la duración en segundos de un archivo de audio."""
        try:
            r = subprocess.run([FFMPEG, '-i', filepath, '-f', 'null', '-'],
                               capture_output=True)
            stderr = r.stderr.decode('utf-8', errors='replace')
            for line in stderr.split('\n'):
                if 'Duration:' in line:
                    try:
                        t = line.split('Duration:')[1].split(',')[0].strip()
                        h, m, s = t.split(':')
                        return int(h) * 3600 + int(m) * 60 + float(s)
                    except:
                        pass
        except Exception:
            pass
        return 0.0

    def _detect_bpm(self, audio_file):
        """Detecta BPM con librosa. Analiza hasta 90s para velocidad. Devuelve float o None."""
        try:
            import librosa
            import numpy as np
            y, sr = librosa.load(audio_file, sr=None, mono=True, duration=90)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            bpm = float(np.atleast_1d(tempo)[0])
            return bpm if 40 < bpm < 300 else None
        except Exception:
            return None

    def _build_atempo_chain(self, ratio):
        """
        Construye cadena de filtros atempo para un ratio dado.
        FFmpeg limita cada filtro a [0.5, 2.0], se encadenan para ratios extremos.
        atempo=r → audio suena r veces más rápido, duración /= r.
        """
        filters = []
        r = ratio
        while r > 2.0:
            filters.append('atempo=2.0')
            r /= 2.0
        while r < 0.5:
            filters.append('atempo=0.5')
            r *= 2.0
        if abs(r - 1.0) > 0.001:
            filters.append(f'atempo={r:.5f}')
        return ','.join(filters) if filters else ''

    def _mix_with_beat(self, vocals, beat, output_mp3, log_fn=None, preview_only=False, clone_voice=False, override_profile=None, harmony_voice=False, vol_voz_override=None, vol_beat_override=None, vol_clone_override=None, start_t=None, duration_t=None, pauta_file=None):
        """
        PROTOCOLO DE MEZCLA INTELIGENTE CON PERFILES (Normal, PRO, Masterizada).
        """
        _log = log_fn or self.proc_log_write

        # Soporte backwards compatible por si se pasan rutas
        if isinstance(vocals, str): vocals = {'file': vocals, 'bpm': None, 'key_idx': None}
        if isinstance(beat, str): beat = {'file': beat, 'bpm': None, 'key_idx': None}
        if isinstance(vocals, dict) and 'voz' in vocals:
            beat = vocals['beat']; vocals = vocals['voz']
            
        vocals_file = vocals['file']
        beat_file = beat['file']

        voz_dur  = self._get_duration(vocals_file)
        beat_dur = self._get_duration(beat_file)
        if voz_dur == 0 or beat_dur == 0:
            _log(f"   ❌ Duración 0 — voz:{voz_dur:.1f}s beat:{beat_dur:.1f}s")
            return

        # ── PASO A: Análisis de BPM ───────────────────────────
        _log("   🔬 Analizando BPM...")
        voz_bpm  = self._detect_bpm(vocals_file)
        beat_bpm = self._detect_bpm(beat_file)

        atempo_str = ''
        ratio      = 1.0

        if voz_bpm and beat_bpm:
            _log(f"   🎤 Voz: {voz_bpm:.1f} BPM  |  🥁 Beat: {beat_bpm:.1f} BPM")

            candidates = {
                'original': beat_bpm,
                'mitad':    beat_bpm * 0.5,
                'doble':    beat_bpm * 2.0,
            }

            best_ratio = 1.0
            best_label = 'sin ajuste'
            best_dist  = 9999.0

            for label, cand_bpm in candidates.items():
                r = voz_bpm / cand_bpm
                if 0.25 <= r <= 4.0:
                    dist = abs(r - 1.0)
                    if dist < best_dist:
                        best_dist  = dist
                        best_ratio = r
                        best_label = label

            ratio = best_ratio

            if abs(ratio - 1.0) > 0.04:
                atempo_str = self._build_atempo_chain(ratio)
                _log(f"   🔧 {best_label}: beat {ratio:.3f}x → {beat_bpm*ratio:.1f} BPM")
            else:
                _log(f"   ✅ BPMs compatibles (ratio {ratio:.3f})")
        else:
            _log("   ⚠️ Sin BPM detectado — mezclando sin ajuste de tempo")

        # ── PASO B: Duraciones ────────────────────────────────
        beat_dur_ajustado = beat_dur / ratio if ratio != 1.0 else beat_dur

        fade_in  = 2.0
        fade_out = 4.0
        fo_start = max(fade_in + 0.5, voz_dur - fade_out)
        beat_needed = voz_dur + fade_out + 0.5

        if beat_dur_ajustado < voz_dur:
            _log(f"   🔄 Beat {beat_dur_ajustado:.1f}s < Voz {voz_dur:.1f}s → loop")
        else:
            _log(f"   ✂️  Beat {beat_dur_ajustado:.1f}s > Voz {voz_dur:.1f}s → fade out")

        # ── PASO C: Construir filtros ──────────────────────────
        profile = override_profile or (self.mix_profile.get() if hasattr(self, 'mix_profile') else 'Normal')
        _log(f"   🎛️ Perfil activo: {profile}")
        
        pitch_filter = ''
        if 'PRO' in profile or 'Masterizada' in profile:
            if vocals.get('key_idx') is not None and beat.get('key_idx') is not None:
                diff = (vocals['key_idx'] - beat['key_idx'])
                if diff > 6: diff -= 12
                elif diff < -6: diff += 12
                if diff != 0:
                    pitch_ratio = 2.0 ** (diff / 12.0)
                    pitch_filter = f'rubberband=pitch={pitch_ratio:.4f},'
                    _log(f"   🎵 Afinación: beat ajustado {diff:+d} semitonos")

        beat_pre = f'[0:a]{pitch_filter}{atempo_str + "," if atempo_str else ""}'

        _bal = getattr(self, 'mix_balance', None)
        _bal_val = _bal.get() if _bal else 'balanced'
        if _bal_val == 'voz':      vol_beat, vol_voz = 0.42, 2.1
        elif _bal_val == 'beat':   vol_beat, vol_voz = 1.05, 1.0
        else:                      vol_beat, vol_voz = 0.68, 1.55
        
        if vol_voz_override is not None: vol_voz = vol_voz_override
        if vol_beat_override is not None: vol_beat = vol_beat_override
        vol_clone = vol_clone_override if vol_clone_override is not None else 0.3

        gentle_chain = ''
        if 'PRO' in profile or 'Masterizada' in profile:
            gentle_chain += 'aecho=0.8:0.88:40:0.3,'
            gentle_chain += 'acompressor=threshold=0.1:ratio=4:attack=5:release=50:makeup=1.5:knee=2.5,'
        else:
            _gentle = getattr(self, 'proc_gentle_master', None)
            if _gentle and _gentle.get():
                gentle_chain += 'highpass=f=80,lowpass=f=12000,anlmdn=s=2:p=0.002:r=0.002,acompressor=threshold=0.5:ratio=2:attack=15:release=120:makeup=1.05:knee=8,alimiter=limit=0.97:attack=5:release=30,'

        beat_filter = (
            beat_pre
            + f'volume={vol_beat:.3f},'
            + f'afade=t=in:st=0:d={fade_in},'
            + f'afade=t=out:st={fo_start:.3f}:d={fade_out},'
            + f'atrim=end={beat_needed:.3f},asetpts=PTS-STARTPTS[beat_raw];'
        )

        voz_filter = (
            f'[1:a]{gentle_chain}volume={vol_voz:.3f},'
            f'afade=t=in:st=0:d={fade_in},'
            f'afade=t=out:st={fo_start:.3f}:d={fade_out}'
        )
        
        if clone_voice and harmony_voice:
            voz_filter += (
                ',asplit=3[v1][v2][v3];'
                f'[v2]aecho=0.8:0.88:80:0.5,aecho=0.8:0.88:120:0.4,volume={vol_clone:.3f}[v2_fx];'
                f'[v3]adelay=1000|1000,rubberband=pitch=1.2599,volume={vol_clone:.3f}[v3_fx];'
                '[v1][v2_fx][v3_fx]amix=inputs=3:duration=longest[voz];'
            )
        elif clone_voice:
            # Duplicar voz: una se queda normal [v1], la otra recibe eco y baja volumen [v2]
            voz_filter += (
                ',asplit=2[v1][v2];'
                f'[v2]aecho=0.8:0.88:80:0.5,aecho=0.8:0.88:120:0.4,volume={vol_clone:.3f}[v2_fx];'
                '[v1][v2_fx]amix=inputs=2:duration=longest[voz];'
            )
        elif harmony_voice:
            voz_filter += (
                ',asplit=2[v1][v3];'
                f'[v3]adelay=1000|1000,rubberband=pitch=1.2599,volume={vol_clone:.3f}[v3_fx];'
                '[v1][v3_fx]amix=inputs=2:duration=longest[voz];'
            )
        else:
            voz_filter += '[voz];'

        pauta_filter = ''
        if pauta_file and os.path.exists(pauta_file):
            pauta_filter = f'[2:a]volume=0.8,aecho=0.8:0.88:40:0.3[pauta];'
            if 'PRO' in profile or 'Masterizada' in profile:
                master_routing = '[voz]asplit=2[voz_mix][voz_sc];[beat_raw][voz_sc]sidechaincompress=threshold=0.08:ratio=4:attack=5:release=60:makeup=1.2[beat];[beat][voz_mix][pauta]amix=inputs=3:duration=longest[mix];'
            else:
                master_routing = '[beat_raw][voz][pauta]amix=inputs=3:duration=longest[mix];'
        else:
            if 'PRO' in profile or 'Masterizada' in profile:
                master_routing = '[voz]asplit=2[voz_mix][voz_sc];[beat_raw][voz_sc]sidechaincompress=threshold=0.08:ratio=4:attack=5:release=60:makeup=1.2[beat];[beat][voz_mix]amix=inputs=2:duration=longest[mix];'
            else:
                master_routing = '[beat_raw][voz]amix=inputs=2:duration=longest[mix];'

        if 'Masterizada' in profile:
            master_fx = 'highpass=f=40,lowpass=f=16000,acompressor=threshold=0.15:ratio=4:attack=5:release=50:makeup=2.5:knee=2.5,equalizer=f=80:width_type=o:width=1.5:g=3,equalizer=f=4000:width_type=o:width=2:g=2.5,alimiter=limit=0.95:attack=2:release=15,loudnorm=I=-12:LRA=7:TP=-1'
        else:
            master_fx = 'highpass=f=40,lowpass=f=16000,acompressor=threshold=0.4:ratio=3:attack=8:release=80:makeup=1.2:knee=6,equalizer=f=80:width_type=o:width=1:g=2,equalizer=f=3000:width_type=o:width=2:g=1.5,equalizer=f=8000:width_type=o:width=2:g=1,alimiter=limit=0.95:attack=3:release=20,loudnorm=I=-14:LRA=9:TP=-1'

        master = master_routing + '[mix]' + master_fx + '[out]'

        end_t = fo_start + fade_out
        cmd = [
            FFMPEG,
            '-stream_loop', '-1', '-i', beat_file,
            '-i', vocals_file,
        ]
        
        if pauta_file and os.path.exists(pauta_file):
            cmd.extend(['-i', pauta_file])
            
        cmd.extend([
            '-filter_complex', beat_filter + voz_filter + pauta_filter + master,
            '-map', '[out]'
        ])
        
        if start_t is not None and duration_t is not None:
            cmd.extend(['-ss', f'{start_t:.3f}', '-t', f'{duration_t:.3f}'])
        elif preview_only:
            cmd.extend(['-t', '15.0'])
        else:
            cmd.extend(['-t', f'{end_t:.3f}'])
            
        cmd.extend(['-y', output_mp3])
        
        if not preview_only:
            # Alta calidad
            cmd = cmd[:-2] + ['-ar', '44100', '-ac', '2', '-b:a', '320k'] + cmd[-2:]
            
        r = subprocess.run(cmd, capture_output=True)

        if r.returncode != 0:
            err = r.stderr.decode('utf-8', errors='replace')[-500:]
            _log(f"   ⚠️ FFmpeg error (rc={r.returncode}): {err}")

    def proc_log_write(self, msg):
        def _do():
            self.proc_log.config(state='normal')
            self.proc_log.insert('end', f"[{datetime.now():%H:%M:%S}] {msg}\n")
            self.proc_log.see('end')
            self.proc_log.config(state='disabled')
        self.root.after(0, _do)

    def matcher_log_write(self, msg):
        def _do():
            self.matcher_log.config(state='normal')
            self.matcher_log.insert('end', f"[{datetime.now():%H:%M:%S}] {msg}\n")
            self.matcher_log.see('end')
            self.matcher_log.config(state='disabled')
        self.root.after(0, _do)

    # ════════════════════════════════════════════════════════
    #  ARTISTA & METADATOS
    # ════════════════════════════════════════════════════════
    def _safe_filename(self, name, maxlen=60):
        """Convierte un título en nombre de archivo seguro para Windows."""
        import re
        name = re.sub(r'[\\/:*?"<>|]', '', name)
        name = re.sub(r'\s+', ' ', name).strip('. ')
        return name[:maxlen] if name else 'Sin_titulo'

    def _suggest_titles(self, text):
        """Sugiere hasta 5 títulos basándose en frases y palabras repetidas en la letra."""
        import re
        from collections import Counter

        if not text: return ['Sin título']
        stop = {'de','la','el','en','y','a','que','es','lo','se','un','una','me','te',
                'le','no','si','mi','tu','su','los','las','por','con','del','al','ya',
                'mas','pero','como','para','yo','ni','hay','bien','todo','vez','aqui',
                'ahi','este','esta','eso','esa','ese','muy','tan','ser','fue','era'}

        clean = re.sub(r'[^\w\sáéíóúüñÁÉÍÓÚÜÑ]', ' ', text.lower())
        words = [w for w in clean.split() if len(w) > 3 and w not in stop]

        # Frases de 2 palabras repetidas (gancho/hook)
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        pc = Counter()
        for line in lines:
            ws = line.split()
            for i in range(len(ws)-1):
                pc[' '.join(ws[i:i+2]).title()] += 1
        top_phrases = [p for p, c in pc.most_common(8) if c >= 2]

        # Palabras más frecuentes
        top_words = [w.title() for w, _ in Counter(words).most_common(6)]

        seen, result = set(), []
        for s in top_phrases + top_words:
            if s.lower() not in seen and len(s) > 4:
                seen.add(s.lower())
                result.append(s)
            if len(result) == 5: break
        return result or ['Sin título']

    def _pick_title(self):
        """Muestra diálogo de sugerencias de título desde el archivo de voz actual."""
        input_f = self.proc_input_file.get().strip()
        if not input_f or not os.path.exists(input_f):
            messagebox.showinfo("Sugerir título",
                                "Primero seleccioná el archivo de voz en la sección ①."); return

        def _run():
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel("small", device="cpu", compute_type="int8")
                segs, _ = model.transcribe(input_f, language='es',
                                           beam_size=3, vad_filter=True)
                text = ' '.join(s.text.strip() for s in segs)
                suggestions = self._suggest_titles(text)
            except Exception:
                suggestions = []
            self.root.after(0, lambda: self._show_title_picker(suggestions))

        self.proc_status_lbl.config(text="⏳ Analizando letra...")
        threading.Thread(target=_run, daemon=True).start()

    def _show_title_picker(self, suggestions):
        self.proc_status_lbl.config(text="")
        if not suggestions:
            messagebox.showinfo("Sin sugerencias",
                                "No se detectó texto. Escribí el título manualmente."); return

        win = tk.Toplevel(self.root)
        win.title("Elegí un título")
        win.geometry("420x280")
        win.configure(bg='#1a1a2e')
        win.grab_set()

        tk.Label(win, text="Títulos sugeridos (elegí uno o escribí el tuyo):",
                 fg='#a8a8b3', bg='#1a1a2e', font=('Arial',9)).pack(pady=(12,4))

        lb = tk.Listbox(win, bg='#16213e', fg='white', font=('Arial',10),
                        selectbackground='#e94560', height=5)
        lb.pack(fill='x', padx=16, pady=4)
        for s in suggestions: lb.insert('end', s)
        lb.select_set(0)

        custom_var = tk.StringVar()
        tk.Label(win, text="O escribí tu propio título:",
                 fg='#a8a8b3', bg='#1a1a2e', font=('Arial',9)).pack(anchor='w', padx=16)
        tk.Entry(win, textvariable=custom_var, bg='#16213e', fg='white',
                 insertbackground='white', relief='flat', font=('Arial',10), bd=4,
                 width=40).pack(padx=16, pady=4)

        def apply():
            custom = custom_var.get().strip()
            if custom:
                self.proc_song_title.set(custom)
            else:
                sel = lb.curselection()
                if sel: self.proc_song_title.set(lb.get(sel[0]))
            win.destroy()

        self._btn(win, "✓ Usar este título", apply, '#e94560',
                  font=('Arial',10,'bold')).pack(pady=8)

    def _tag_mp3(self, mp3_file, title, artist, genre, bpm, year, lyrics):
        """Embebe metadatos ID3 en el MP3 usando mutagen."""
        try:
            from mutagen.mp3 import MP3
            from mutagen.id3 import (ID3, TIT2, TPE1, TALB, TCON, TBPM,
                                     TYER, USLT, ID3NoHeaderError)
            try:    tags = ID3(mp3_file)
            except ID3NoHeaderError: tags = ID3()

            tags['TIT2'] = TIT2(encoding=3, text=title)
            tags['TPE1'] = TPE1(encoding=3, text=artist)
            tags['TALB'] = TALB(encoding=3, text=f"{artist}")
            tags['TCON'] = TCON(encoding=3, text=genre)
            tags['TYER'] = TYER(encoding=3, text=str(year))
            if bpm:
                tags['TBPM'] = TBPM(encoding=3, text=str(int(bpm)))
            if lyrics:
                tags['USLT'] = USLT(encoding=3, lang='spa', desc='Lyrics', text=lyrics)
            tags.save(mp3_file)
        except ImportError:
            self.proc_log_write("   ⚠️ mutagen no instalado — ejecutá instalar.bat")
        except Exception as e:
            self.proc_log_write(f"   ⚠️ Tagging falló: {e}")

    def _generate_proof(self, voz_file, mp3_file, title, artist, lyrics,
                         bpm, key, out_dir, ts):
        """Genera documento de autoría con hash SHA256 del archivo de voz original."""
        import hashlib
        sha256 = '(no disponible)'
        if os.path.exists(voz_file):
            with open(voz_file, 'rb') as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()

        dur = self._get_duration(mp3_file)
        mins, secs = int(dur // 60), int(dur % 60)

        proof = (
            f"DOCUMENTO DE AUTORÍA — {title}\n"
            f"{'═'*60}\n"
            f"ARTISTA        : {artist}\n"
            f"TÍTULO         : {title}\n"
            f"GÉNERO         : {self.artist_genre.get()}\n"
            f"FECHA/HORA     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"DURACIÓN       : {mins}:{secs:02d} min\n"
            f"BPM            : {f'{bpm:.1f}' if bpm else '?'}\n"
            f"TONALIDAD      : {key}\n"
            f"{'─'*60}\n"
            f"ARCHIVO VOZ ORIGINAL:\n"
            f"   Nombre  : {os.path.basename(voz_file)}\n"
            f"   SHA-256 : {sha256}\n\n"
            f"PROCESO APLICADO:\n"
            f"   • Voz grabada en live\n"
            f"   • Separada del fondo con Demucs IA (htdemucs_ft)\n"
            f"   • Limpiada con FFmpeg (highpass/lowpass/anlmdn/compand)\n"
            f"   • Mezclada con beat instrumental propio\n"
            f"   • Masterización: -14 LUFS (estándar Spotify/Apple Music)\n"
            f"{'─'*60}\n"
            f"LETRA (extracto):\n"
            + ('\n'.join(lyrics.split('\n')[:12]) if lyrics else '(sin transcripción)')
            + f"\n{'═'*60}\n"
            f"El hash SHA-256 del archivo de voz permite verificar la\n"
            f"autenticidad ante plataformas, sellos o disputas de copyright.\n"
            f"Guardá este archivo junto al MP3 original de voz.\n"
            f"{'═'*60}\n"
        )

        path = os.path.join(out_dir, f"AUTORIA_{ts}.txt")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(proof)
        return path

    def _clean_temp_files(self, session_dir):
        """Elimina archivos WAV intermedios de la sesión."""
        for pattern in ('*_raw.wav', '*_seg*.wav', '*_voz_limpia.wav'):
            for f in glob.glob(os.path.join(session_dir, pattern)):
                try: os.remove(f)
                except: pass
        # Carpeta de Demucs
        for d in glob.glob(os.path.join(session_dir, 'htdemucs*')):
            try:
                import shutil; shutil.rmtree(d)
            except: pass

    def _write_export_summary(self, session_dir, final_files, artist, genre, ts):
        """Genera RESUMEN_EXPORTAR.txt con checklist y próximos pasos."""
        files_list = '\n'.join(
            f"   ✅ {os.path.basename(mp3)}" for _, _, mp3 in final_files
            if os.path.exists(mp3)
        )
        summary = (
            f"RESUMEN DE EXPORTACIÓN — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"{'═'*60}\n"
            f"ARTISTA : {artist}\n"
            f"GÉNERO  : {genre}\n"
            f"CARPETA : {session_dir}\n\n"
            f"ARCHIVOS LISTOS:\n{files_list}\n\n"
            f"{'─'*60}\n"
            f"CHECKLIST PARA SUBIR A PLATAFORMAS:\n\n"
            f"  □ 1. Abrí el MP3 en VLC y escuchalo completo\n"
            f"  □ 2. Verificá que la voz se escucha clara sobre el beat\n"
            f"  □ 3. Elegí o generá la imagen de tapa (ver *_IMAGEN_PROMPT.txt)\n"
            f"      → Suno AI, Midjourney, DALL-E, Adobe Firefly\n"
            f"      → Tamaño: 3000×3000 px, formato JPG o PNG\n"
            f"  □ 4. Registrá la obra antes de subir:\n"
            f"      → safecreative.org (gratis)\n"
            f"      → BMI / ASCAP (si estás en EE.UU.)\n"
            f"      → SADAIC / AADI (si estás en Argentina)\n"
            f"  □ 5. Distribuí con:\n"
            f"      → DistroKid (desde $22/año, Spotify + Apple + 150 tiendas)\n"
            f"      → TuneCore (por canción o suscripción)\n"
            f"      → CD Baby (pago único + royalties)\n"
            f"      → Amuse (opción gratuita limitada)\n"
            f"  □ 6. Al subir, tenés lista la info:\n"
            f"      → Título, Artista, Género: ver metadatos del MP3\n"
            f"      → Letra completa: ver *_LETRA_*.txt\n"
            f"      → Prueba de creación: ver AUTORIA_*.txt\n"
            f"{'═'*60}\n"
            f"Si alguna plataforma reclama copyright por el beat:\n"
            f"  → Presentá AUTORIA_*.txt como evidencia\n"
            f"  → El beat es IA/propio, la voz es humana y original\n"
            f"  → El hash SHA-256 prueba que la voz existía en esta fecha\n"
            f"{'═'*60}\n"
        )
        path = os.path.join(session_dir, f"RESUMEN_EXPORTAR.txt")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(summary)

    # ════════════════════════════════════════════════════════
    #  FIRMA DE AUDIO / MARCA
    # ════════════════════════════════════════════════════════
    def _browse_brand(self):
        f = filedialog.askopenfilename(
            title="Seleccioná tu firma/marca de audio",
            filetypes=[("Audio","*.mp3 *.wav *.ogg *.m4a"),("Todos","*.*")])
        if f: self.proc_brand_file.set(f)

    def _add_brand_to_file(self, main_file, output_file):
        """
        Inserta el audio de firma en inicio / medio / final del track.
        Devuelve True si lo logró, False en caso de error.
        """
        brand_file = self.proc_brand_file.get().strip()
        if not brand_file or not os.path.exists(brand_file):
            return False

        main_dur  = self._get_duration(main_file)
        brand_dur = self._get_duration(brand_file)
        if main_dur == 0 or brand_dur == 0:
            return False

        vol = self.proc_brand_vol.get() / 100.0
        pos = self.proc_brand_pos.get()

        if pos == 'inicio':
            delay_ms = 300                                        # 0.3s desde el principio
        elif pos == 'final':
            delay_ms = int(max(0, main_dur - brand_dur - 0.2) * 1000)
        else:  # medio
            delay_ms = int(max(0, (main_dur - brand_dur) / 2) * 1000)

        r = subprocess.run([
            FFMPEG,
            '-i', main_file,
            '-i', brand_file,
            '-filter_complex', (
                f'[1:a]volume={vol:.3f},'
                f'adelay={delay_ms}|{delay_ms}[marca];'
                f'[0:a][marca]amix=inputs=2:duration=first[out]'
            ),
            '-map', '[out]',
            '-b:a', '320k',
            output_file, '-y'
        ], capture_output=True)
        return r.returncode == 0

    # ════════════════════════════════════════════════════════
    #  TRANSCRIPCIÓN VOZ → LETRA + PROMPT DE IMAGEN
    # ════════════════════════════════════════════════════════
    def _transcribe_audio(self, audio_file, out_dir, base, ts, log_fn=None):
        """
        Transcribe con faster-whisper y organiza el texto como letra de canción.
        Devuelve (texto_plano, bpm, key) o None si falla.
        """
        _log = log_fn or self.proc_log_write
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            _log("❌ faster-whisper no instalado — ejecutá instalar.bat")
            return None

        try:
            lang_raw = self.proc_lang.get()
            lang = None if 'Auto' in lang_raw else lang_raw.split('—')[0].strip()

            _log("   ⏬ Cargando Whisper (primera vez descarga ~150MB)...")
            model = WhisperModel("small", device="cpu", compute_type="int8")

            _log("   🔊 Transcribiendo...")
            segments, info = model.transcribe(audio_file, language=lang,
                                              beam_size=5, vad_filter=True)
            seg_list = list(segments)
            if not seg_list:
                _log("   ⚠️ No se detectó voz en el audio")
                return None

            # Organizar como letra: cada segmento = 1 línea, verso cada 4 líneas
            lines = [s.text.strip() for s in seg_list if s.text.strip()]
            verses = []
            for i in range(0, len(lines), 4):
                verses.append('\n'.join(lines[i:i+4]))
            lyrics = '\n\n'.join(verses)
            full_text = ' '.join(lines)

            # Detectar BPM y key del audio
            bpm_val, key_val = None, '?'
            try:
                import librosa, numpy as np
                y, sr = librosa.load(audio_file, sr=None, mono=True, duration=60)
                tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                bpm_val = float(np.atleast_1d(tempo)[0])
                chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
                key_idx = int(np.argmax(chroma.mean(axis=1)))
                key_val = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][key_idx]
            except Exception:
                pass

            # Guardar letra
            txt_path = os.path.join(out_dir, f"{base}_LETRA_{ts}.txt")
            detected_lang = info.language if hasattr(info, 'language') else '?'
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(f"LETRA — {base}\n")
                f.write(f"{'═'*54}\n")
                bpm_str = f"{bpm_val:.1f}" if bpm_val else "?"
                f.write(f"Idioma: {detected_lang}  |  BPM: {bpm_str}  |  Tono: {key_val}\n\n")
                f.write(lyrics + '\n')

            _log(f"   ✅ Letra guardada: {os.path.basename(txt_path)}")
            for line in lines[:4]:
                _log(f"      {line}")
            if len(lines) > 4:
                _log(f"      ... ({len(lines)} líneas en total)")

            return full_text, bpm_val, key_val

        except Exception as e:
            _log(f"   ⚠️ Transcripción falló: {e}")
            return None

    def _generate_image_prompt(self, text, bpm, key, out_dir, base, ts,
                               log_fn=None, title='', artist=''):
        """
        Genera 2 prompts de imagen (portada Spotify) a partir de la letra y el análisis.
        Exporta como .txt junto a la canción.
        """
        _log = log_fn or self.proc_log_write
        words = text.lower().split() if text else []

        # Detectar ambiente dominante por palabras clave
        dark   = sum(1 for w in words if w in
                     {'noche','oscuro','dolor','solo','lluvia','muerte','sombra','frio',
                      'silencio','perdido','vacio','lagrimas','tristeza'})
        energy = sum(1 for w in words if w in
                     {'fuego','poder','victoria','fuerza','lucha','grito','calle',
                      'real','sangre','guerra','triunfo','corona','dinero'})
        love   = sum(1 for w in words if w in
                     {'amor','corazon','sentir','beso','querer','extraño','mia',
                      'juntos','siempre','forever','bella','bonita'})
        spirit = sum(1 for w in words if w in
                     {'dios','fe','alma','espiritu','cielo','bendicion','oracion',
                      'gracias','paz','luz','esperanza'})

        scores = {'oscuro': dark, 'energético': energy, 'romántico': love, 'espiritual': spirit}
        dominant = max(scores, key=scores.get) if any(scores.values()) else 'urbano'

        styles = {
            'oscuro':     ("dark moody cinematic",        "noir city, neon reflections, deep shadows"),
            'energético': ("powerful intense raw",         "urban motion blur, fire, graffiti walls"),
            'romántico':  ("warm emotional intimate",      "golden hour portrait, soft bokeh light"),
            'espiritual': ("ethereal uplifting divine",    "light rays through clouds, sacred geometry"),
            'urbano':     ("authentic street gritty",      "urban concrete, raw street expression"),
        }
        mood, visual = styles.get(dominant, styles['urbano'])
        tempo_feel = "slow heavy" if (bpm or 100) < 90 else "fast energetic" if (bpm or 100) > 130 else "mid-tempo groove"

        # Título y artista para el prompt
        title_str  = title  if title  else 'Sin título'
        artist_str = artist if artist else ''
        by_str     = f" by {artist_str}" if artist_str and artist_str != 'Artista' else ''

        # Prompt 1 — portada fotorrealista
        p1 = (
            f"Spotify album cover for the song '{title_str}'{by_str}, "
            f"{visual}, {mood} atmosphere, Spanish urban rapper authentic portrait, "
            f"professional worldwide hit cover, square 1:1 format, "
            f"cinematic lighting, ultra HD 4K. No text, no logos, no watermarks."
        )

        # Prompt 2 — portada abstracta / arte gráfico
        p2 = (
            f"Spotify cover art for '{title_str}'{by_str}, "
            f"abstract graphic design, {key} key color palette, "
            f"{tempo_feel}, {mood} energy, modern minimalist, "
            f"square 1:1, ultra HD. No text, no logos."
        )

        bpm_str = f"{bpm:.0f}" if bpm else "?"
        prompt_txt = (
            f"PROMPT DE IMAGEN — {title_str}\n"
            f"{'═'*54}\n"
            f"Artista: {artist_str or '—'}  |  BPM: {bpm_str}  |  Tono: {key}  |  Ambiente: {dominant}\n\n"
            f"── PROMPT 1 · Portada fotorrealista (Midjourney / DALL-E / Ideogram) ──\n"
            f'"{p1}"\n\n'
            f"── PROMPT 2 · Portada abstracta / arte gráfico ──\n"
            f'"{p2}"\n\n'
            f"Midjourney: añadir  --ar 1:1 --v 6 --style raw\n"
            f"{'═'*54}\n"
        )

        prompt_path = os.path.join(out_dir, f"{base}_IMAGEN_PROMPT_{ts}.txt")
        with open(prompt_path, 'w', encoding='utf-8') as f:
            f.write(prompt_txt)
        _log(f"   🖼️ Prompt imagen guardado")
        _log(f"      P1: {p1[:65]}...")
        return prompt_path

    # ════════════════════════════════════════════════════════
    #  EMPAREJADOR PRO — LÓGICA
    # ════════════════════════════════════════════════════════

    # Compatibilidad de tonos: intervalo en semitonos → puntuación (círculo de quintas)
    _KEY_COMPAT = {0:100, 7:90, 5:88, 4:82, 9:80, 3:75, 8:70, 2:62, 10:60, 1:45, 11:42, 6:35}

    def _key_compat_score(self, ki_a, ki_b):
        diff = abs(ki_a - ki_b) % 12
        return self._KEY_COMPAT.get(diff, 50)

    def _analyze_track(self, filepath):
        """Analiza BPM, tono dominante y energía de un archivo. Devuelve dict."""
        try:
            import librosa, numpy as np
            y, sr = librosa.load(filepath, sr=None, mono=True, duration=90)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            bpm = float(np.atleast_1d(tempo)[0])
            bpm = bpm if 40 < bpm < 300 else None
            chroma  = librosa.feature.chroma_cqt(y=y, sr=sr)
            key_idx = int(np.argmax(chroma.mean(axis=1)))
            rms      = float(librosa.feature.rms(y=y).mean())
            energy   = float(librosa.amplitude_to_db(np.array([rms]))[0])
            duration = librosa.get_duration(y=y, sr=sr)
            keys = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
            return {'file': filepath, 'name': os.path.basename(filepath),
                    'bpm': bpm, 'key_idx': key_idx, 'key': keys[key_idx],
                    'energy': energy, 'duration': duration, 'error': None}
        except Exception as e:
            return {'file': filepath, 'name': os.path.basename(filepath),
                    'bpm': None, 'key_idx': None, 'key': '?',
                    'energy': None, 'duration': 0, 'error': str(e)}

    def _compute_compat(self, voz, beat):
        """Calcula score 0-100 de compatibilidad entre una voz y un beat."""
        ws, wt = 0.0, 0.0
        sc = {}

        # BPM (45%) — considera relaciones 1:1, 1:2, 2:1
        if voz['bpm'] and beat['bpm']:
            vb, bb = voz['bpm'], beat['bpm']
            best_r = min([vb/bb, vb/(bb*2), (vb*2)/bb], key=lambda r: abs(r-1.0))
            diff   = abs(best_r - 1.0)
            sc['bpm'] = max(0.0, 100.0 - diff * 280.0)
            ws += sc['bpm'] * 45; wt += 45

        # Tono (35%) — círculo de quintas
        if voz['key_idx'] is not None and beat['key_idx'] is not None:
            sc['key'] = self._key_compat_score(voz['key_idx'], beat['key_idx'])
            ws += sc['key'] * 35; wt += 35

        # Energía (20%) — diferencia de dB
        if voz['energy'] is not None and beat['energy'] is not None:
            sc['energy'] = max(0.0, 100.0 - abs(voz['energy'] - beat['energy']) * 4.0)
            ws += sc['energy'] * 20; wt += 20

        total = (ws / wt) if wt > 0 else 0.0

        if   total >= 80: label, tag = '⭐ Excelente',       'excelente'
        elif total >= 65: label, tag = '✅ Bueno',            'bueno'
        elif total >= 50: label, tag = '⚠️  Regular',        'regular'
        else:             label, tag = '❌ No recomendado',   'no_recmd'

        # Ratio BPM del mejor candidato armónico
        if voz['bpm'] and beat['bpm']:
            vb, bb = voz['bpm'], beat['bpm']
            best_r = min([vb/bb, vb/(bb*2), (vb*2)/bb], key=lambda r: abs(r-1.0))
        else:
            best_r = 1.0

        return {'voz': voz, 'beat': beat, 'score': total,
                'bpm_score': sc.get('bpm', 0), 'key_score': sc.get('key', 0),
                'energy_score': sc.get('energy', 0),
                'label': label, 'tag': tag, 'bpm_ratio': best_r}

    # ── Carga de archivos ────────────────────────────────────
    _AUDIO_EXTS = ('*.mp3','*.wav','*.wma','*.m4a','*.ogg','*.flac')

    def _match_load_folder(self, folder):
        files = []
        for ext in self._AUDIO_EXTS:
            files += glob.glob(os.path.join(folder, ext))
        return sorted(files)

    def _match_browse_voz(self):
        f = filedialog.askdirectory(title="Carpeta de voces")
        if f:
            self.match_voz_folder.set(f)
            self._match_set_voz(self._match_load_folder(f))

    def _match_add_voz(self):
        files = filedialog.askopenfilenames(
            title="Agregar archivos de voz",
            filetypes=[("Audio","*.mp3 *.wav *.wma *.m4a *.ogg *.flac"),("Todos","*.*")])
        if files:
            all_f = list(self.match_voz_files)
            for f in files:
                if f not in all_f: all_f.append(f)
            self._match_set_voz(all_f)

    def _match_browse_beat(self):
        f = filedialog.askdirectory(title="Carpeta de beats")
        if f:
            self.match_beat_folder.set(f)
            self._match_set_beat(self._match_load_folder(f))

    def _match_add_beat(self):
        files = filedialog.askopenfilenames(
            title="Agregar beats",
            filetypes=[("Audio","*.mp3 *.wav *.wma *.m4a *.ogg *.flac"),("Todos","*.*")])
        if files:
            all_f = list(self.match_beat_files)
            for f in files:
                if f not in all_f: all_f.append(f)
            self._match_set_beat(all_f)

    def _match_set_voz(self, files):
        self.match_voz_files = files
        self.match_voz_lb.delete(0, 'end')
        for f in files: self.match_voz_lb.insert('end', os.path.basename(f))
        self.match_voz_count.config(text=f"{len(files)} archivo(s)")

    def _match_set_beat(self, files):
        self.match_beat_files = files
        self.match_beat_lb.delete(0, 'end')
        for f in files: self.match_beat_lb.insert('end', os.path.basename(f))
        self.match_beat_count.config(text=f"{len(files)} archivo(s)")

    def _match_remove(self, which):
        """Quita los ítems seleccionados del listbox (selección múltiple con Ctrl/Shift o Delete)."""
        if which == 'voz':
            lb    = self.match_voz_lb
            files = list(self.match_voz_files)
        else:
            lb    = self.match_beat_lb
            files = list(self.match_beat_files)
        sel = lb.curselection()
        if not sel:
            return
        for i in reversed(sel):
            if 0 <= i < len(files):
                files.pop(i)
        if which == 'voz':
            self._match_set_voz(files)
        else:
            self._match_set_beat(files)

    def _match_clear(self, which):
        if which == 'voz':
            self._match_set_voz([])
            self.match_voz_folder.set('')
        else:
            self._match_set_beat([])
            self.match_beat_folder.set('')

    def _match_browse_out(self):
        d = filedialog.askdirectory(title="Carpeta de salida para mezclas")
        if d: self.match_out_folder.set(d)

    def _match_sort(self, col):
        """Ordena la tabla al hacer click en el encabezado."""
        items = [(self.match_tree.set(k, col), k) for k in self.match_tree.get_children('')]
        try:
            items.sort(key=lambda x: float(x[0].replace('%','').strip()), reverse=True)
        except ValueError:
            items.sort(reverse=True)
        for idx, (_, k) in enumerate(items):
            self.match_tree.move(k, '', idx)

    # ── Análisis ─────────────────────────────────────────────
    def start_match_analysis(self):
        if self.match_running: return
        if not self.match_voz_files:
            messagebox.showerror("Error","Agregá al menos una voz."); return
        if not self.match_beat_files:
            messagebox.showerror("Error","Agregá al menos un beat."); return
        self.match_running = True
        self.match_btn.config(state='disabled', bg='#333')
        self.match_bar.config(value=0,
            maximum=len(self.match_voz_files) + len(self.match_beat_files))
        for r in self.match_tree.get_children(): self.match_tree.delete(r)
        self.match_status.config(text="⏳ Analizando archivos...")
        self.match_pairs = []
        threading.Thread(target=self._analysis_thread, daemon=True).start()

    def _analysis_thread(self):
        try:
            done = 0
            def upd(msg, d):
                self.root.after(0, lambda: self.match_status.config(text=msg))
                self.root.after(0, lambda v=d: self.match_bar.config(value=v))

            # ── Analizar voces
            voz_data = []
            for f in self.match_voz_files:
                upd(f"🎤 Analizando voz {done+1}/{len(self.match_voz_files)}: "
                    f"{os.path.basename(f)[:30]}", done)
                voz_data.append(self._analyze_track(f))
                done += 1

            # ── Analizar beats
            beat_data = []
            for f in self.match_beat_files:
                upd(f"🥁 Analizando beat {done - len(self.match_voz_files)+1}/"
                    f"{len(self.match_beat_files)}: {os.path.basename(f)[:30]}", done)
                beat_data.append(self._analyze_track(f))
                done += 1

            # ── Calcular todos los pares N×M
            self.root.after(0, lambda: self.match_status.config(text="🔬 Calculando compatibilidad..."))
            pairs = [self._compute_compat(v, b) for v in voz_data for b in beat_data]
            pairs.sort(key=lambda p: p['score'], reverse=True)
            self.match_pairs = pairs

            self.root.after(0, lambda: self._populate_match_tree(pairs))
        except Exception as e:
            self.root.after(0, lambda: self.match_status.config(text=f"❌ Error: {e}"))
        finally:
            self.match_running = False
            self.root.after(0, lambda: self.match_btn.config(state='normal', bg='#533483'))

    def _populate_match_tree(self, pairs):
        for r in self.match_tree.get_children(): self.match_tree.delete(r)
        threshold = self.match_threshold.get()
        shown = 0
        for p in pairs:
            if p['score'] < threshold: continue
            bv = f"{p['voz']['bpm']:.1f}"   if p['voz']['bpm']  else "?"
            bb = f"{p['beat']['bpm']:.1f}"  if p['beat']['bpm'] else "?"
            self.match_tree.insert('', 'end', values=(
                p['voz']['name'], p['beat']['name'],
                bv, bb,
                f"{p['bpm_score']:.0f}%",
                f"{p['key_score']:.0f}%",
                f"{p['energy_score']:.0f}%",
                f"{p['score']:.0f}%",
                p['label']
            ), tags=(p['tag'],))
            shown += 1
        above = sum(1 for p in pairs if p['score'] >= threshold)
        self.match_status.config(
            text=f"✅ {len(pairs)} pares — {above} sobre {threshold}% — "
                 f"{shown} mostrados"
        )

    # ── Mezcla por lotes ──────────────────────────────────────
    # ── Asignación óptima ────────────────────────────────────
    def _find_best_assignment(self):
        """
        Algoritmo greedy de asignación bipartita:
        cada voz se empareja con UN solo beat y cada beat con UNA sola voz,
        maximizando el score total (los pares ya vienen ordenados por score desc).
        Devuelve (seleccionados, unused_voz_dict, unused_beat_dict).
        """
        used_voz, used_beat = set(), set()
        selected = []
        for p in self.match_pairs:          # ya están ordenados por score desc
            vf, bf = p['voz']['file'], p['beat']['file']
            if vf not in used_voz and bf not in used_beat:
                selected.append(p)
                used_voz.add(vf)
                used_beat.add(bf)
        all_voz  = {p['voz']['file']:  p['voz']  for p in self.match_pairs}
        all_beat = {p['beat']['file']: p['beat'] for p in self.match_pairs}
        unused_voz  = {f: d for f, d in all_voz.items()  if f not in used_voz}
        unused_beat = {f: d for f, d in all_beat.items() if f not in used_beat}
        return selected, unused_voz, unused_beat

    def show_best_assignment(self):
        """Muestra diálogo con la asignación óptima 1 voz ↔ 1 beat sin repetidos."""
        if not self.match_pairs:
            messagebox.showinfo("Sin análisis","Primero analizá la compatibilidad."); return

        selected, unused_voz, unused_beat = self._find_best_assignment()
        threshold = self.match_threshold.get()
        good = [p for p in selected if p['score'] >= threshold]
        weak = [p for p in selected if p['score'] <  threshold]

        n_voz  = len({p['voz']['file']  for p in self.match_pairs})
        n_beat = len({p['beat']['file'] for p in self.match_pairs})

        win = tk.Toplevel(self.root)
        win.title("🎯 Mejor Asignación — Sin Repetidos")
        win.geometry("640x560")
        win.configure(bg='#1a1a2e')
        win.grab_set()

        # ── Header ──
        hdr = tk.Frame(win, bg='#0f3460', pady=10); hdr.pack(fill='x')
        tk.Label(hdr, text=f"  🎯  {n_voz} voces × {n_beat} beats  →  {len(selected)} pares únicos",
                 fg='white', bg='#0f3460', font=('Arial',12,'bold')).pack(anchor='w', padx=12)
        stats = (f"  ⭐ {sum(1 for p in good if p['score']>=80)} excelentes  "
                 f"✅ {sum(1 for p in good if 65<=p['score']<80)} buenos  "
                 f"⚠️ {len(weak)} bajo umbral  "
                 f"🔵 {len(unused_beat)} beats libres  "
                 f"🎤 {len(unused_voz)} voces libres")
        tk.Label(hdr, text=stats, fg='#a8a8b3', bg='#0f3460',
                 font=('Arial',9)).pack(anchor='w', padx=12)

        # ── Lista de pares seleccionados ──
        tk.Label(win, text="  PARES SELECCIONADOS (ordenados por compatibilidad):",
                 fg='#e94560', bg='#1a1a2e', font=('Arial',9,'bold')).pack(anchor='w', padx=10, pady=(8,2))

        lf = tk.Frame(win, bg='#1a1a2e'); lf.pack(fill='both', expand=True, padx=10)
        lb = tk.Listbox(lf, bg='#16213e', fg='white', font=('Courier',9),
                        selectbackground='#533483', activestyle='none')
        sb = ttk.Scrollbar(lf, orient='vertical', command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        colors = {'excelente':'#00ff88','bueno':'#77cc33','regular':'#f5a623','no_recmd':'#e94560'}

        for idx, p in enumerate(good):
            vn = os.path.splitext(p['voz']['name'])[0][:28]
            bn = os.path.splitext(p['beat']['name'])[0][:28]
            icon = '⭐' if p['score'] >= 80 else '✅'
            lb.insert('end', f"  {icon} {int(p['score']):3d}%  {vn:<28}  ←→  {bn}")
            lb.itemconfig(idx, fg=colors.get(p['tag'], 'white'))

        for idx2, p in enumerate(weak, len(good)):
            vn = os.path.splitext(p['voz']['name'])[0][:28]
            bn = os.path.splitext(p['beat']['name'])[0][:28]
            lb.insert('end', f"  ⚠️  {int(p['score']):3d}%  {vn:<28}  ←→  {bn}  [bajo umbral]")
            lb.itemconfig(idx2, fg='#555555')

        # ── Libres ──
        if unused_beat or unused_voz:
            free_f = tk.Frame(win, bg='#1a1a2e'); free_f.pack(fill='x', padx=10, pady=(4,0))
            if unused_beat:
                tk.Label(free_f, text=f"🔵 Beats sin par ({len(unused_beat)}): " +
                         "  ".join(d['name'][:20] for d in list(unused_beat.values())[:4]),
                         fg='#445566', bg='#1a1a2e', font=('Arial',8)).pack(anchor='w')
            if unused_voz:
                tk.Label(free_f, text=f"🎤 Voces sin par ({len(unused_voz)}): " +
                         "  ".join(d['name'][:20] for d in list(unused_voz.values())[:4]),
                         fg='#445566', bg='#1a1a2e', font=('Arial',8)).pack(anchor='w')

        # ── Botones ──
        bf2 = tk.Frame(win, bg='#0f3460', pady=8); bf2.pack(fill='x', side='bottom')

        def _mix(pairs_list):
            win.destroy()
            self._do_batch_mix(pairs_list)

        if good:
            self._btn(bf2, f"⚡ Mezclar {len(good)} buenos",
                      lambda: _mix(good), '#1a6b3a',
                      font=('Arial',10,'bold'), padx=12, pady=6).pack(side='left', padx=10)
        if weak:
            self._btn(bf2, f"⚡ Mezclar todos ({len(selected)})",
                      lambda: _mix(selected), '#533483',
                      font=('Arial',10,'bold'), padx=12, pady=6).pack(side='left', padx=4)
        self._btn(bf2, "✕ Cerrar", win.destroy, '#333',
                  font=('Arial',10,'bold'), padx=12, pady=6).pack(side='right', padx=10)

    def _do_batch_mix(self, pairs_to_mix):
        """Lanza la mezcla por lotes sobre una lista de pares ya definida."""
        if not pairs_to_mix:
            messagebox.showinfo("Sin pares","No hay pares para mezclar."); return
        if self.match_running: return
        out_dir = self.match_out_folder.get().strip() or \
                  os.path.join(os.path.expanduser("~"), "TikTok_Lives", "Mezclas")
        os.makedirs(out_dir, exist_ok=True)
        self.match_running = True
        self.match_bar.config(value=0, maximum=len(pairs_to_mix))
        self.match_mix_status.config(text=f"⏳ Mezclando {len(pairs_to_mix)} pares...")
        threading.Thread(target=self._batch_mix_thread,
                         args=(pairs_to_mix, out_dir), daemon=True).start()

    def start_batch_mix(self, mode):
        """Lanza mezcla sin confirmación (llamado desde 'Mejor Asignación')."""
        if self.match_running: return
        if not self.match_pairs:
            messagebox.showinfo("Sin análisis","Primero analizá la compatibilidad."); return
        threshold = self.match_threshold.get()
        above     = [p for p in self.match_pairs if p['score'] >= threshold]

        if mode is None:
            sel = self.match_tree.selection()
            if not sel:
                messagebox.showinfo("Sin selección","Seleccioná pares en la tabla."); return
            all_items    = self.match_tree.get_children()
            pairs_to_mix = [above[all_items.index(s)] for s in sel
                            if all_items.index(s) < len(above)]
        elif mode == 'all':
            pairs_to_mix = above
        else:
            pairs_to_mix = above[:mode]

        self._do_batch_mix(pairs_to_mix)

    def preview_batch_mix(self, mode):
        """Muestra diálogo de confirmación con lista de pares antes de mezclar, o pre-escucha uno."""
        if self.match_running: return
        if not self.match_pairs:
            messagebox.showinfo("Sin análisis","Primero analizá la compatibilidad."); return
        threshold = self.match_threshold.get()
        above     = [p for p in self.match_pairs if p['score'] >= threshold]

        if mode is None or mode == 'listen':
            sel = self.match_tree.selection()
            if not sel:
                messagebox.showinfo("Sin selección","Seleccioná un par en la tabla."); return
            all_items    = self.match_tree.get_children()
            pairs_to_mix = [above[all_items.index(s)] for s in sel
                            if all_items.index(s) < len(above)]
            label = f"{len(pairs_to_mix)} seleccionado(s)"
            
            if mode == 'listen':
                self._preview_single_mix(pairs_to_mix[0])
                return
        elif mode == 'all':
            pairs_to_mix = above
            label = f"todos ({len(above)})"
        else:
            pairs_to_mix = above[:mode]
            label = f"Top {mode}"

        if not pairs_to_mix:
            messagebox.showinfo("Sin pares","No hay pares sobre el umbral."); return

        win = tk.Toplevel(self.root)
        win.title("Confirmar mezcla por lotes")
        win.geometry("540x400")
        win.configure(bg='#1a1a2e')
        win.grab_set()

        hdr = tk.Frame(win, bg='#0f3460', pady=10); hdr.pack(fill='x')
        tk.Label(hdr, text=f"⚡  Mezclar {label}",
                 fg='#e94560', bg='#0f3460', font=('Arial',12,'bold')).pack(anchor='w', padx=14)
        tk.Label(hdr, text=f"  {len(pairs_to_mix)} par(es) van a renderizarse. "
                           f"Revisá la lista y confirmá.",
                 fg='#a8a8b3', bg='#0f3460', font=('Arial',9)).pack(anchor='w', padx=14)

        lf = tk.Frame(win, bg='#1a1a2e'); lf.pack(fill='both', expand=True, padx=14, pady=10)
        lb = tk.Listbox(lf, bg='#16213e', fg='white', font=('Courier',8),
                        activestyle='none', selectmode='browse')
        sb = ttk.Scrollbar(lf, orient='vertical', command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        colors = {'excelente':'#00ff88','bueno':'#77cc33','regular':'#f5a623','no_recmd':'#e94560'}
        for i, p in enumerate(pairs_to_mix):
            vn = os.path.splitext(p['voz']['name'])[0][:25]
            bn = os.path.splitext(p['beat']['name'])[0][:25]
            lb.insert('end', f"  {int(p['score']):3d}%  {vn}  ←→  {bn}")
            lb.itemconfig(i, fg=colors.get(p['tag'], 'white'))

        bf = tk.Frame(win, bg='#0f3460', pady=8); bf.pack(fill='x', side='bottom')

        def _go():
            win.destroy()
            self._do_batch_mix(pairs_to_mix)

        self._btn(bf, f"⚡ Mezclar {len(pairs_to_mix)} pares", _go, '#1a6b3a',
                  font=('Arial',11,'bold'), padx=14, pady=6).pack(side='left', padx=10)
        self._btn(bf, "✕ Cancelar", win.destroy, '#333',
                  font=('Arial',10,'bold'), padx=12, pady=6).pack(side='right', padx=10)

    def _batch_mix_thread(self, pairs, out_dir):
        try:
            ts      = datetime.now().strftime('%Y%m%d_%H%M%S')
            session = os.path.join(out_dir, f"batch_{ts}")
            os.makedirs(session, exist_ok=True)
            self.matcher_log_write(f"{'─'*44}")
            self.matcher_log_write(f"🎯 {len(pairs)} par(es) → {os.path.basename(session)}")
            ok = fail = 0
            year   = datetime.now().year
            artist = self.artist_name.get().strip() or 'Artista'
            genre  = self.artist_genre.get()

            for i, p in enumerate(pairs, 1):
                vname = os.path.splitext(p['voz']['name'])[0][:28]
                bname = os.path.splitext(p['beat']['name'])[0][:28]
                score = int(p['score'])

                # ── Subcarpeta por par ─────────────────────────
                pair_dir = os.path.join(session, f"{i:02d}_{score}pct_{vname[:20]}")
                os.makedirs(pair_dir, exist_ok=True)
                out_f = os.path.join(pair_dir, f"FINAL_{vname[:18]}+{bname[:18]}.mp3")

                self.root.after(0, lambda n=p['voz']['name'], ii=i:
                    self.match_mix_status.config(text=f"🎵 {ii}/{len(pairs)}: {n[:35]}"))
                self.matcher_log_write(
                    f"  [{i}/{len(pairs)}] {vname[:22]} ←→ {bname[:22]} ({score}%)")

                # ── Mezcla ────────────────────────────────────
                self._mix_with_beat(p, None, out_f, log_fn=self.matcher_log_write)
                if not os.path.exists(out_f):
                    self.matcher_log_write(f"      ❌ Mezcla falló")
                    fail += 1
                    self.root.after(0, lambda v=i: self.match_bar.config(value=v))
                    continue
                self.matcher_log_write(f"      ✅ FINAL.mp3")
                ok += 1

                # ── Transcripción → Letra ─────────────────────
                # Transcribe el FINAL.mp3 mezclado: la voz es más clara sobre el beat.
                lyrics_text, bpm_val, key_val = '', None, '?'
                if self.proc_transcribe.get():
                    self.matcher_log_write(f"      📝 Transcribiendo FINAL.mp3...")
                    result = self._transcribe_audio(out_f, pair_dir, vname[:18], ts,
                                                    log_fn=self.matcher_log_write)
                    if result:
                        lyrics_text, bpm_val, key_val = result
                else:
                    bpm_val = p['voz'].get('bpm')
                    key_val = p['voz'].get('key', '?')

                # ── Título (de la UI, de la letra, o fallback) ─
                title = self.proc_song_title.get().strip()
                if not title and lyrics_text:
                    suggestions = self._suggest_titles(lyrics_text)
                    title = suggestions[0] if suggestions else ''
                if not title:
                    title = f"{vname[:20]} + {bname[:20]}"

                # ── Renombrar MP3 con el título real ──────────
                safe = self._safe_filename(title)
                named_f = os.path.join(pair_dir, f"{safe}.mp3")
                try:
                    os.rename(out_f, named_f)
                    out_f = named_f
                    self.matcher_log_write(f"      💾 {safe}.mp3")
                except Exception:
                    pass  # si falla el rename, out_f sigue como FINAL_...mp3

                # ── Marca de audio (después del rename para tomar el título) ──
                brand_f = self.proc_brand_file.get().strip()
                if brand_f and os.path.exists(brand_f):
                    branded_name = self._safe_filename(f"{title} Branding")
                    branded = os.path.join(pair_dir, f"{branded_name}.mp3")
                    if self._add_brand_to_file(out_f, branded):
                        self.matcher_log_write(f"      🎙️ {branded_name}.mp3")

                # ── Prompt de imagen ──────────────────────────
                if self.proc_transcribe.get() and lyrics_text and self.proc_img_prompt.get():
                    self._generate_image_prompt(lyrics_text, bpm_val, key_val,
                                                pair_dir, vname[:18], ts,
                                                log_fn=self.matcher_log_write,
                                                title=title, artist=artist)

                # ── ID3 Tags ──────────────────────────────────
                if self.proc_tag_mp3.get():
                    self._tag_mp3(out_f, title, artist, genre, bpm_val, year, lyrics_text)
                    self.matcher_log_write(f"      🏷️ ID3: \"{title}\"")

                # ── Autoría / prueba hash ─────────────────────
                if self.proc_gen_proof.get():
                    self._generate_proof(p['voz']['file'], out_f, title,
                                         artist, lyrics_text, bpm_val, key_val,
                                         pair_dir, ts)
                    self.matcher_log_write(f"      🔏 Autoría guardada")

                self.root.after(0, lambda v=i: self.match_bar.config(value=v))

            resumen = f"✅ {ok} OK" + (f"  ❌ {fail} fallidas" if fail else "")
            self.matcher_log_write(f"{'─'*44}")
            self.matcher_log_write(resumen + f" → {os.path.basename(session)}")
            self.root.after(0, lambda:
                self.match_mix_status.config(
                    text=f"✅ {ok}/{len(pairs)} listas → {session}"))
        except Exception as e:
            self.matcher_log_write(f"❌ Error: {e}")
            self.root.after(0, lambda: self.match_mix_status.config(text=f"❌ {e}"))
        finally:
            self.match_running = False

    def _preview_single_mix(self, pair):
        """Abre el Estudio de Mezcla Visual Multicanal para el par seleccionado."""
        win = tk.Toplevel(self.root)
        vn = os.path.basename(pair['voz']['name'])[:20]
        bn = os.path.basename(pair['beat']['name'])[:20]
        win.title(f"🎛️ Mini-DAW Estudio de Mezcla: {vn} + {bn}")
        win.geometry("1000x640")
        win.configure(bg='#1a1a2e')
        win.grab_set()

        hdr = tk.Frame(win, bg='#0f3460', pady=5)
        hdr.pack(fill='x')
        tk.Label(hdr, text="🎛️ Estudio de Mezcla Visual Completo", fg='#e94560', bg='#0f3460', font=('Arial', 12, 'bold')).pack(side='left', padx=10)
        
        ctrl_f = tk.Frame(hdr, bg='#0f3460')
        ctrl_f.pack(side='right', padx=10)
        
        tk.Label(ctrl_f, text="Perfil:", fg='white', bg='#0f3460').pack(side='left')
        mix_profile_var = tk.StringVar(value=self.mix_profile.get() if hasattr(self, 'mix_profile') else 'Normal')
        cb = ttk.Combobox(ctrl_f, textvariable=mix_profile_var, values=['Normal', 'PRO', 'Masterizada'], width=12, state='readonly')
        cb.pack(side='left', padx=5)
        
        clone_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrl_f, text="🎤 Clon Reverb", variable=clone_var, fg='#00ff88', bg='#0f3460', selectcolor='#1a1a2e', activebackground='#0f3460').pack(side='left', padx=5)

        harmony_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrl_f, text="🎶 Armonía (Coros)", variable=harmony_var, fg='#ff00ff', bg='#0f3460', selectcolor='#1a1a2e', activebackground='#0f3460').pack(side='left', padx=5)

        # Volúmenes
        vol_f = tk.Frame(win, bg='#1a1a2e')
        vol_f.pack(pady=5, fill='x', padx=20)
        
        def _make_slider(parent, label, default, color):
            f = tk.Frame(parent, bg='#1a1a2e')
            f.pack(side='left', expand=True)
            tk.Label(f, text=label, fg=color, bg='#1a1a2e', font=('Arial', 9, 'bold')).pack()
            s = tk.Scale(f, from_=0.0, to=3.0, resolution=0.1, orient='horizontal', bg='#1a1a2e', fg='white', highlightthickness=0)
            s.set(default)
            s.pack()
            return s
            
        vol_voz_scale = _make_slider(vol_f, "Voz Principal", 1.5, '#00ff88')
        vol_clone_scale = _make_slider(vol_f, "Efectos (Clon/Armonía)", 0.3, '#ff00ff')
        vol_beat_scale = _make_slider(vol_f, "Beat (Instrumental)", 0.8, '#4da6ff')

        state = {
            'y_voz': None, 'y_beat': None, 'sr': 8000, 'dur': 0, 
            'start': 0, 'end': 0, 'drawing': False,
            'drag_mode': 'new', 'drag_start_click_t': 0, 'drag_orig_start': 0, 'drag_orig_end': 0,
            'zoom': 1.0, 'offset': 0.0,
            'playing': False, 'play_proc': None, 'play_start_t': 0, 'play_start_sec': 0,
            'paused': False, 'paused_sec': 0.0
        }

        # Canvas Doble en un solo widget
        cv = tk.Canvas(win, width=960, height=200, bg='#0f3460', highlightthickness=0)
        cv.pack(pady=10)
        
        status_lbl = tk.Label(win, text="⏳ Cargando audio...", fg='#a8a8b3', bg='#1a1a2e', font=('Arial',9))
        status_lbl.pack()
        
        f2 = tk.Frame(win, bg='#1a1a2e'); f2.pack(pady=5)
        tk.Label(f2, text="Inicio (s):", fg='white', bg='#1a1a2e').pack(side='left')
        t_start = tk.Entry(f2, width=8); t_start.pack(side='left', padx=5)
        t_start.insert(0, "0.0")
        tk.Label(f2, text="Fin (s):", fg='white', bg='#1a1a2e').pack(side='left')
        t_end = tk.Entry(f2, width=8); t_end.pack(side='left', padx=5)
        t_end.insert(0, "0.0")
        
        def _time_to_x(t):
            view_dur = state['dur'] / state['zoom']
            if view_dur == 0: return 0
            return ((t - state['offset']) / view_dur) * 960

        def _x_to_time(x):
            view_dur = state['dur'] / state['zoom']
            return state['offset'] + (x / 960) * view_dur

        def _draw_waveforms():
            if state['y_voz'] is None: return
            cv.delete("wave")
            
            view_dur = state['dur'] / state['zoom']
            start_sample = int(state['offset'] * state['sr'])
            end_sample = int((state['offset'] + view_dur) * state['sr'])
            
            import numpy as np
            
            # Dibujar Voz (Arriba)
            y_v = state['y_voz'][start_sample:end_sample]
            if len(y_v) > 0:
                chunks = np.array_split(y_v, 960)
                for i, chunk in enumerate(chunks):
                    if len(chunk) == 0: continue
                    m = np.max(np.abs(chunk))
                    h = max(1, m * 90)
                    cv.create_line(i, 50 - h/2, i, 50 + h/2, fill='#00ff88', tags="wave")
                    
            # Dibujar Beat (Abajo)
            y_b = state['y_beat'][start_sample:end_sample]
            if len(y_b) > 0:
                chunks = np.array_split(y_b, 960)
                for i, chunk in enumerate(chunks):
                    if len(chunk) == 0: continue
                    m = np.max(np.abs(chunk))
                    h = max(1, m * 90)
                    cv.create_line(i, 150 - h/2, i, 150 + h/2, fill='#4da6ff', tags="wave")
                    
            cv.tag_lower("wave")
            # Separador central
            cv.create_line(0, 100, 960, 100, fill='#1a1a2e', tags="wave")
            
            _update_selection_rect()

        def _update_selection_rect():
            cv.delete("sel")
            x1 = _time_to_x(state['start'])
            x2 = _time_to_x(state['end'])
            if x1 < 0: x1 = 0
            if x2 > 960: x2 = 960
            if x2 > x1:
                cv.create_rectangle(x1, 0, x2, 200, fill='#533483', stipple='gray25', tags="sel", outline='')
                cv.create_line(x1, 0, x1, 200, fill='#00ff88', tags="sel")
                cv.create_line(x2, 0, x2, 200, fill='#e94560', tags="sel")
            cv.tag_lower("sel")
            
            t_start.delete(0, 'end'); t_start.insert(0, f"{state['start']:.2f}")
            t_end.delete(0, 'end'); t_end.insert(0, f"{state['end']:.2f}")

        def _on_zoom(event):
            factor = 1.2 if event.delta > 0 else 0.8
            t_mouse = _x_to_time(event.x)
            new_zoom = max(1.0, min(100.0, state['zoom'] * factor))
            new_view_dur = state['dur'] / new_zoom
            
            ratio = event.x / 960
            new_offset = t_mouse - (ratio * new_view_dur)
            new_offset = max(0.0, min(new_offset, state['dur'] - new_view_dur))
            
            state['zoom'] = new_zoom
            state['offset'] = new_offset
            _draw_waveforms()

        def _on_click(event):
            t = _x_to_time(event.x)
            state['drag_start_click_t'] = t
            state['drag_orig_start'] = state['start']
            state['drag_orig_end'] = state['end']
            
            margin = (state['dur'] / state['zoom']) * 0.04 # 4% de la vista actual para agarrar los bordes más fácil
            if abs(t - state['start']) < margin:
                state['drag_mode'] = 'left'
            elif abs(t - state['end']) < margin:
                state['drag_mode'] = 'right'
            elif state['start'] < t < state['end']:
                state['drag_mode'] = 'center'
            else:
                state['drag_mode'] = 'new'
                state['start'] = t
                state['end'] = t
            
            state['drawing'] = True
            _update_selection_rect()

        def _on_drag(event):
            if not state['drawing']: return
            t = max(0, min(state['dur'], _x_to_time(event.x)))
            
            if state['drag_mode'] == 'new':
                state['end'] = t
            elif state['drag_mode'] == 'left':
                state['start'] = min(t, state['end'] - 0.1)
            elif state['drag_mode'] == 'right':
                state['end'] = max(t, state['start'] + 0.1)
            elif state['drag_mode'] == 'center':
                delta = t - state['drag_start_click_t']
                dur_sel = state['drag_orig_end'] - state['drag_orig_start']
                new_s = max(0, state['drag_orig_start'] + delta)
                new_e = new_s + dur_sel
                if new_e > state['dur']:
                    new_e = state['dur']
                    new_s = new_e - dur_sel
                state['start'] = new_s
                state['end'] = new_e
                
            _update_selection_rect()

        def _on_release(event):
            state['drawing'] = False
            if state['start'] > state['end']:
                state['start'], state['end'] = state['end'], state['start']
            if abs(state['start'] - state['end']) < 0.1:
                state['start'] = 0
                state['end'] = state['dur']
            _update_selection_rect()

        cv.bind("<Button-1>", _on_click)
        cv.bind("<B1-Motion>", _on_drag)
        cv.bind("<ButtonRelease-1>", _on_release)
        cv.bind("<MouseWheel>", _on_zoom)

        def _load_audio():
            try:
                import librosa
                v_file = pair['voz']['file']
                b_file = pair['beat']['file']
                y_v, sr = librosa.load(v_file, sr=8000, mono=True)
                y_b, _ = librosa.load(b_file, sr=8000, mono=True)
                
                dur_v = len(y_v) / sr
                dur_b = len(y_b) / sr
                dur = max(dur_v, dur_b)
                
                import numpy as np
                if dur_v < dur: y_v = np.pad(y_v, (0, int((dur - dur_v) * sr)))
                if dur_b < dur: 
                    reps = int(np.ceil(dur / dur_b))
                    y_b = np.tile(y_b, reps)[:int(dur * sr)]
                
                state['y_voz'] = y_v
                state['y_beat'] = y_b
                state['sr'] = sr
                state['dur'] = dur
                state['end'] = dur
                
                self.root.after(0, lambda: _draw_waveforms())
                self.root.after(0, lambda: status_lbl.config(text="✅ Listo. Hacé zoom, seleccioná, ajustá y dale a Play."))
            except Exception as e:
                self.root.after(0, lambda: status_lbl.config(text=f"❌ Error visual: {e}"))

        threading.Thread(target=_load_audio, daemon=True).start()
        
        def _playhead_loop():
            if not state['playing']: return
            import time
            if state['paused']:
                elapsed = state['paused_sec']
            else:
                elapsed = state['play_start_sec'] + (time.time() - state['play_start_t'])
                
            cv.delete("playhead")
            sel_dur = state['end'] - state['start']
            
            if elapsed <= sel_dur:
                x = _time_to_x(state['start'] + elapsed)
                if 0 <= x <= 960:
                    cv.create_line(x, 0, x, 200, fill='#ffff00', width=2, tags="playhead")
                if not state['paused']:
                    win.after(30, _playhead_loop)
            else:
                state['playing'] = False
                cv.delete("playhead")

        def _play(start_offset=0.0):
            import subprocess, time
            if state['play_proc']:
                subprocess.run(['taskkill', '/F', '/IM', 'ffplay.exe'], capture_output=True)
                
            status_lbl.config(text="⏳ Mezclando... (puede tomar unos seg)")
            
            out_dir = os.path.join(os.path.expanduser("~"), ".cache", "tiktok_lives")
            os.makedirs(out_dir, exist_ok=True)
            tmp_out = os.path.join(out_dir, "preview_mix.wav")
            if os.path.exists(tmp_out): os.remove(tmp_out)
            
            def _run():
                prof = mix_profile_var.get()
                pauta_file = None
                if hasattr(self, 'pauta_cb') and self.pauta_cb.get():
                    pauta_file = os.path.join(os.path.expanduser("~"), "TikTok_Lives", "Pautas", self.pauta_cb.get())
                clone = clone_var.get()
                harm = harmony_var.get()
                v_voz = vol_voz_scale.get()
                v_beat = vol_beat_scale.get()
                v_clo = vol_clone_scale.get()
                
                real_start = state['start'] + start_offset
                real_dur = (state['end'] - state['start']) - start_offset
                
                # Pasamos start_t y duration_t a _mix_with_beat para procesar solo esa parte y rápido
                self._mix_with_beat(
                    pair, None, tmp_out, log_fn=lambda x: None, 
                    preview_only=False, clone_voice=clone, override_profile=prof,
                    harmony_voice=harm, vol_voz_override=v_voz, vol_beat_override=v_beat,
                    vol_clone_override=v_clo, start_t=real_start, duration_t=state['dur'], pauta_file=pauta_file
                )
                
                if os.path.exists(tmp_out):
                    self.root.after(0, lambda: status_lbl.config(text=f"▶️ Reproduciendo ({prof})..."))
                    state['play_proc'] = subprocess.Popen(['ffplay', '-nodisp', '-autoexit', tmp_out])
                    state['playing'] = True
                    state['paused'] = False
                    state['play_start_t'] = time.time()
                    state['play_start_sec'] = start_offset
                    self.root.after(0, _playhead_loop)
                else:
                    self.root.after(0, lambda: status_lbl.config(text="❌ Error al generar mezcla"))
            
            threading.Thread(target=_run, daemon=True).start()

        def _pause():
            if state['playing'] and not state['paused']:
                import time, subprocess
                state['paused_sec'] = state['play_start_sec'] + (time.time() - state['play_start_t'])
                state['paused'] = True
                if state['play_proc']:
                    subprocess.run(['taskkill', '/F', '/IM', 'ffplay.exe'], capture_output=True)
                status_lbl.config(text="⏸️ Pausado")
            elif state['paused']:
                _play(start_offset=state['paused_sec'])

        def _stop():
            state['playing'] = False
            state['paused'] = False
            cv.delete("playhead")
            import subprocess
            subprocess.run(['taskkill', '/F', '/IM', 'ffplay.exe'], capture_output=True)
            status_lbl.config(text="⏹️ Detenido")

        def _export():
            _stop()
            pauta_file = None
            if hasattr(self, 'pauta_cb') and self.pauta_cb.get():
                pauta_file = os.path.join(os.path.expanduser("~"), "TikTok_Lives", "Pautas", self.pauta_cb.get())
            status_lbl.config(text="⏳ Exportando mezcla final en Alta Calidad...")
            
            out_dir = self.match_out_folder.get().strip() or \
                      os.path.join(os.path.expanduser("~"), "TikTok_Lives", "Mezclas")
            os.makedirs(out_dir, exist_ok=True)
            
            prof = mix_profile_var.get()
            clone = clone_var.get()
            harm = harmony_var.get()
            v_voz = vol_voz_scale.get()
            v_beat = vol_beat_scale.get()
            v_clo = vol_clone_scale.get()
            
            vn = os.path.splitext(os.path.basename(pair['voz']['name']))[0][:15]
            bn = os.path.splitext(os.path.basename(pair['beat']['name']))[0][:15]
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            final_out = os.path.join(out_dir, f"FINAL_{vn}_{bn}_{ts}.mp3")
            
            def _run_exp():
                self._mix_with_beat(
                    pair, None, final_out, log_fn=lambda x: None, 
                    preview_only=False, clone_voice=clone, override_profile=prof,
                    harmony_voice=harm, vol_voz_override=v_voz, vol_beat_override=v_beat,
                    vol_clone_override=v_clo, pauta_file=pauta_file
                )
                if os.path.exists(final_out):
                    self.root.after(0, lambda: messagebox.showinfo("Exportación Exitosa", f"Tu mezcla se ha guardado en:\n{final_out}"))
                    self.root.after(0, lambda: status_lbl.config(text=f"✅ Guardado en: {final_out}"))
                else:
                    self.root.after(0, lambda: status_lbl.config(text="❌ Error al exportar"))
                    
            threading.Thread(target=_run_exp, daemon=True).start()

        bf = tk.Frame(win, bg='#1a1a2e')
        bf.pack(pady=10, fill='x')
        
        # Botones de reproducción a la izquierda
        play_f = tk.Frame(bf, bg='#1a1a2e')
        play_f.pack(side='left', padx=10)
        self._btn(play_f, "▶️ Escuchar Selección", lambda: _play(0.0), '#1a6b3a', font=('Arial',10,'bold')).pack(side='left', padx=5)
        self._btn(play_f, "⏯️ Pausa/Reanudar", _pause, '#f5a623', font=('Arial',10,'bold')).pack(side='left', padx=5)
        self._btn(play_f, "⏹️ Detener", _stop, '#e94560', font=('Arial',10,'bold')).pack(side='left', padx=5)
        
        # Botones de acción a la derecha
        act_f = tk.Frame(bf, bg='#1a1a2e')
        act_f.pack(side='right', padx=10)
        
        pauta_f = tk.Frame(act_f, bg='#1a1a2e')
        pauta_f.pack(side='left', padx=(0, 20))
        tk.Label(pauta_f, text="🎙️ Pauta:", fg='white', bg='#1a1a2e', font=('Arial',9)).pack(side='left', padx=2)
        self.pauta_cb = ttk.Combobox(pauta_f, state='readonly', width=12, font=('Arial',8))
        self.pauta_cb.pack(side='left', padx=2)
        self.pauta_btn = self._btn(pauta_f, "🎤 Grabar Pauta", lambda: self.toggle_pauta_record(self.pauta_btn, self.pauta_cb), '#533483', font=('Arial',9,'bold'))
        self.pauta_btn.pack(side='left', padx=5)
        self.root.after(0, lambda: self._refresh_pautas_cb(self.pauta_cb))
        
        self._btn(act_f, "💾 Exportar Mix Final", _export, '#533483', font=('Arial',10,'bold')).pack(side='left', padx=5)
        self._btn(act_f, "✕ Cerrar", lambda: [_stop(), win.destroy()], '#333', font=('Arial',10,'bold')).pack(side='left', padx=5)

    def _refresh_pautas_cb(self, cb):
        import os
        pautas_dir = os.path.join(os.path.expanduser("~"), "TikTok_Lives", "Pautas")
        if not os.path.exists(pautas_dir):
            cb['values'] = []
            return
        files = [f for f in os.listdir(pautas_dir) if f.lower().endswith('.wav')]
        cb['values'] = files
        if files and not cb.get():
            cb.current(0)

    def toggle_pauta_record(self, btn, cb):
        if not hasattr(self, 'pauta_recording'):
            self.pauta_recording = False
            import queue
            self.pauta_q = queue.Queue()

        if self.pauta_recording:
            # stop
            self.pauta_recording = False
            btn.config(text="🎤 Grabar Pauta", bg='#533483')
            return
        
        # start
        self.pauta_recording = True
        btn.config(text="⏹️ Detener Grabación", bg='#e94560')
        
        def _record():
            try:
                import sounddevice as sd, soundfile as sf, os
                from datetime import datetime
                fs = 44100
                pautas_dir = os.path.join(os.path.expanduser("~"), "TikTok_Lives", "Pautas")
                os.makedirs(pautas_dir, exist_ok=True)
                filename = os.path.join(pautas_dir, f"Pauta_{datetime.now().strftime('%H%M%S')}.wav")
                
                with sf.SoundFile(filename, mode='x', samplerate=fs, channels=1) as file:
                    with sd.InputStream(samplerate=fs, channels=1, callback=lambda indata, frames, time, status: self.pauta_q.put(indata.copy())):
                        while self.pauta_recording:
                            file.write(self.pauta_q.get())
                
                self.root.after(0, lambda: self._refresh_pautas_cb(cb))
                self.root.after(0, lambda: messagebox.showinfo("Pauta Guardada", f"Pauta guardada en:\n{filename}"))
                self.root.after(0, lambda: cb.set(os.path.basename(filename)))
            except Exception as e:
                self.pauta_recording = False
                self.root.after(0, lambda: messagebox.showerror("Error", f"Error al grabar (revisa tu micrófono):\n{e}"))
                self.root.after(0, lambda: btn.config(text="🎤 Grabar Pauta", bg='#533483'))
                
        import threading
        threading.Thread(target=_record, daemon=True).start()

    def _open_audio_editor(self, listbox):
        """Abre un mini-editor para el archivo seleccionado en la lista."""
        sel = listbox.curselection()
        if not sel: return
        filename = listbox.get(sel[0])
        # Find absolute path
        filepath = None
        for f in self.match_voz_files:
            if os.path.basename(f) == filename: filepath = f; break
        if not filepath: return

        win = tk.Toplevel(self.root)
        win.title(f"✂️ Editor Visual PRO: {filename[:30]}")
        win.geometry("820x400")
        win.configure(bg='#1a1a2e')
        win.grab_set()

        tk.Label(win, text="✂️ Recorte Visual (con Zoom y Playhead)", fg='#e94560', bg='#1a1a2e', font=('Arial', 12, 'bold')).pack(pady=5)
        
        state = {
            'y': None, 'sr': 8000, 'dur': 0, 
            'start': 0, 'end': 0, 'drawing': False,
            'drag_mode': 'new', 'drag_start_click_t': 0, 'drag_orig_start': 0, 'drag_orig_end': 0,
            'zoom': 1.0, 'offset': 0.0,
            'playing': False, 'play_proc': None, 'play_start_t': 0, 'play_start_sec': 0,
            'paused': False, 'paused_sec': 0.0
        }

        cv = tk.Canvas(win, width=760, height=120, bg='#0f3460', highlightthickness=0)
        cv.pack(pady=5)
        
        status_lbl = tk.Label(win, text="⏳ Cargando forma de onda...", fg='#a8a8b3', bg='#1a1a2e', font=('Arial',9))
        status_lbl.pack()

        f2 = tk.Frame(win, bg='#1a1a2e'); f2.pack(pady=5)
        tk.Label(f2, text="Inicio (s):", fg='white', bg='#1a1a2e').pack(side='left')
        t_start = tk.Entry(f2, width=8); t_start.pack(side='left', padx=5)
        t_start.insert(0, "0.0")
        tk.Label(f2, text="Fin (s):", fg='white', bg='#1a1a2e').pack(side='left')
        t_end = tk.Entry(f2, width=8); t_end.pack(side='left', padx=5)
        t_end.insert(0, "0.0")
        tk.Label(f2, text=" | ", fg='#a8a8b3', bg='#1a1a2e').pack(side='left')
        dur_lbl = tk.Label(f2, text="Duración: 0.00s", fg='#00ff88', bg='#1a1a2e', font=('Arial', 9, 'bold'))
        dur_lbl.pack(side='left', padx=5)

        def _time_to_x(t):
            view_dur = state['dur'] / state['zoom']
            if view_dur == 0: return 0
            return ((t - state['offset']) / view_dur) * 760

        def _x_to_time(x):
            view_dur = state['dur'] / state['zoom']
            return state['offset'] + (x / 760) * view_dur

        def _draw_waveform_canvas():
            if state['y'] is None: return
            cv.delete("wave")
            
            view_dur = state['dur'] / state['zoom']
            start_sample = int(state['offset'] * state['sr'])
            end_sample = int((state['offset'] + view_dur) * state['sr'])
            
            y_view = state['y'][start_sample:end_sample]
            if len(y_view) == 0: return
            
            import numpy as np
            chunks = np.array_split(y_view, 760)
            
            for i, chunk in enumerate(chunks):
                if len(chunk) == 0: continue
                m = np.max(np.abs(chunk))
                h = max(1, m * 110)
                cv.create_line(i, 60 - h/2, i, 60 + h/2, fill='#00ff88', tags="wave")
            
            cv.tag_lower("wave")
            _update_selection_rect()

        def _update_selection_rect():
            cv.delete("sel")
            if state['dur'] > 0:
                x1 = _time_to_x(state['start'])
                x2 = _time_to_x(state['end'])
                cv.create_rectangle(x1, 0, x2, 120, fill='#533483', stipple='gray50', outline='#e94560', width=2, tags="sel")
                dur_lbl.config(text=f"Duración: {abs(state['end'] - state['start']):.2f}s")
                cv.tag_raise("playhead")

        def _on_click(e):
            if state['dur'] == 0: return
            t = max(0, min(state['dur'], _x_to_time(e.x)))
            
            view_dur = state['dur'] / state['zoom']
            tol = view_dur * 0.015
            
            if abs(t - state['start']) < tol:
                state['drag_mode'] = 'start'
            elif abs(t - state['end']) < tol:
                state['drag_mode'] = 'end'
            elif state['start'] < t < state['end']:
                state['drag_mode'] = 'center'
                state['drag_start_click_t'] = t
                state['drag_orig_start'] = state['start']
                state['drag_orig_end'] = state['end']
            else:
                state['drag_mode'] = 'new'
                state['start'] = t; state['end'] = t
                
            state['drawing'] = True
            _update_selection_rect()

        def _on_drag(e):
            if not state['drawing'] or state['dur'] == 0: return
            t = max(0, min(state['dur'], _x_to_time(e.x)))
            
            if state['drag_mode'] == 'start':
                state['start'] = min(t, state['end'])
            elif state['drag_mode'] == 'end':
                state['end'] = max(t, state['start'])
            elif state['drag_mode'] == 'center':
                delta = t - state['drag_start_click_t']
                new_start = state['drag_orig_start'] + delta
                new_end = state['drag_orig_end'] + delta
                if new_start < 0:
                    new_end -= new_start; new_start = 0
                if new_end > state['dur']:
                    new_start -= (new_end - state['dur']); new_end = state['dur']
                state['start'] = new_start; state['end'] = new_end
            else:
                state['end'] = t
                
            _update_selection_rect()

        def _on_release(e):
            if not state['drawing']: return
            state['drawing'] = False
            if state['start'] > state['end']:
                state['start'], state['end'] = state['end'], state['start']
            t_start.delete(0, 'end'); t_start.insert(0, f"{state['start']:.2f}")
            t_end.delete(0, 'end'); t_end.insert(0, f"{state['end']:.2f}")
            _update_selection_rect()

        def _on_mousewheel(e):
            if state['dur'] == 0: return
            t_mouse = _x_to_time(e.x)
            
            if e.delta > 0:
                state['zoom'] = min(50.0, state['zoom'] * 1.5)
            else:
                state['zoom'] = max(1.0, state['zoom'] / 1.5)
                
            view_dur = state['dur'] / state['zoom']
            new_offset = t_mouse - (e.x / 760) * view_dur
            new_offset = max(0, min(state['dur'] - view_dur, new_offset))
            state['offset'] = new_offset
            
            _draw_waveform_canvas()

        cv.bind("<ButtonPress-1>", _on_click)
        cv.bind("<B1-Motion>", _on_drag)
        cv.bind("<ButtonRelease-1>", _on_release)
        cv.bind("<MouseWheel>", _on_mousewheel)
        
        def _load_audio():
            try:
                import librosa, numpy as np
                y, sr = librosa.load(filepath, sr=8000, mono=True)
                dur = len(y) / sr
                state['y'] = y; state['sr'] = sr; state['dur'] = dur; state['end'] = dur
                
                self.root.after(0, lambda: status_lbl.config(text="✅ Audio listo. Rueda de ratón (Scroll) para hacer Zoom."))
                self.root.after(0, lambda: t_end.delete(0, 'end'))
                self.root.after(0, lambda: t_end.insert(0, f"{dur:.2f}"))
                self.root.after(0, _draw_waveform_canvas)
            except Exception as e:
                self.root.after(0, lambda: status_lbl.config(text=f"❌ Error: {e}"))

        threading.Thread(target=_load_audio, daemon=True).start()
        
        def _playhead_loop():
            if not state['playing']: return
            import time
            elapsed = time.time() - state['play_start_t']
            current_sec = state['play_start_sec'] + elapsed
            
            e = float(t_end.get().strip() or state['dur'])
            state['paused_sec'] = current_sec # save for pause
            
            cv.delete("playhead")
            if current_sec <= e and state['play_proc'] and state['play_proc'].poll() is None:
                x = _time_to_x(current_sec)
                cv.create_line(x, 0, x, 120, fill='#ffff00', width=2, tags="playhead")
                win.after(30, _playhead_loop)
            else:
                state['playing'] = False
                state['paused'] = False
                cv.delete("playhead")

        def _play_selection():
            if state['playing']: _stop_playback(clear_playhead=True)
            
            if state['paused'] and state['paused_sec'] > 0:
                s = state['paused_sec']
            else:
                s = float(t_start.get().strip() or 0)
                
            e = float(t_end.get().strip() or state['dur'])
            duracion = e - s
            if duracion <= 0: return
            
            state['paused'] = False
            import time
            state['play_proc'] = subprocess.Popen(['ffplay', '-nodisp', '-autoexit', '-ss', str(s), '-t', str(duracion), filepath])
            state['playing'] = True
            state['play_start_t'] = time.time()
            state['play_start_sec'] = s
            _playhead_loop()
            
        def _pause_playback():
            if not state['playing']: return
            state['playing'] = False
            state['paused'] = True
            subprocess.run(['taskkill', '/F', '/IM', 'ffplay.exe'], capture_output=True)
            
        def _stop_playback(clear_playhead=True):
            state['playing'] = False
            state['paused'] = False
            state['paused_sec'] = 0.0
            if clear_playhead: cv.delete("playhead")
            subprocess.run(['taskkill', '/F', '/IM', 'ffplay.exe'], capture_output=True)

        f1 = tk.Frame(win, bg='#1a1a2e'); f1.pack(pady=5)
        self._btn(f1, "▶️ Escuchar", _play_selection, '#1a6b3a', font=('Arial',10,'bold')).pack(side='left', padx=5)
        self._btn(f1, "⏸️ Pausa", _pause_playback, '#e68a00', font=('Arial',10,'bold')).pack(side='left', padx=5)
        self._btn(f1, "⏹️ Detener", _stop_playback, '#e94560', font=('Arial',10,'bold')).pack(side='left', padx=5)

        def apply_trim():
            _stop_playback(clear_playhead=True)
            s, e = t_start.get().strip(), t_end.get().strip()
            duracion = float(e) - float(s)
            if duracion <= 0:
                messagebox.showerror("Error", "La selección no es válida.")
                return
                
            base_name = os.path.splitext(os.path.basename(filepath))[0]
            custom_name = tk.simpledialog.askstring("Nombre", "Nombre para el archivo recortado:", initialvalue=f"{base_name}_recortado")
            
            if not custom_name: return # Canceló
            
            import re
            custom_name = re.sub(r'[\\/*?:"<>|]', "", custom_name)
            ext = os.path.splitext(filepath)[1]
            out_f = os.path.join(os.path.dirname(filepath), custom_name + ext)
            
            win.destroy()
            self.match_mix_status.config(text=f"⏳ Recortando audio ({duracion:.1f}s)...")
            def _cut():
                subprocess.run([FFMPEG, '-i', filepath, '-ss', s, '-t', str(duracion), '-c', 'copy', out_f, '-y'], capture_output=True)
                if os.path.exists(out_f):
                    self.root.after(0, lambda: self._match_add_specific_file(out_f, listbox))
                    self.root.after(0, lambda: self.match_mix_status.config(text="✅ Audio recortado"))
            threading.Thread(target=_cut, daemon=True).start()

        self._btn(win, "✂️ Guardar Recorte", apply_trim, '#533483', font=('Arial',10,'bold')).pack(pady=5)

    def _match_add_specific_file(self, filepath, listbox):
        if listbox == self.match_voz_lb:
            files = list(self.match_voz_files)
            if filepath not in files: files.append(filepath)
            self._match_set_voz(files)
        else:
            files = list(self.match_beat_files)
            if filepath not in files: files.append(filepath)
            self._match_set_beat(files)

    # ════════════════════════════════════════════════════════
    #  DRAG & DROP
    # ════════════════════════════════════════════════════════
    def _parse_drop_path(self, raw):
        """Convierte el string de tkinterdnd2 a una ruta limpia (maneja espacios y {})."""
        raw = raw.strip()
        if raw.startswith('{'):
            # Ruta con espacios: {C:/mi archivo.mp3} — toma solo el primer archivo
            path = raw.split('}')[0][1:]
        else:
            path = raw.split()[0]
        return path.replace('\\', '/')

    def _on_drop_audio(self, event, var, entry):
        path = self._parse_drop_path(event.data)
        entry.config(bg='#16213e')
        if os.path.isfile(path):
            var.set(path)
        else:
            messagebox.showerror("Error", f"No se reconoce como archivo:\n{path}")

    def _bind_drop(self, entry, var):
        """Registra drag & drop en un Entry si tkinterdnd2 está disponible."""
        if not _HAS_DND:
            return
        entry.drop_target_register(DND_FILES)
        entry.dnd_bind('<<DragEnter>>', lambda e: entry.config(bg='#1a4a6e'))
        entry.dnd_bind('<<DragLeave>>', lambda e: entry.config(bg='#16213e'))
        entry.dnd_bind('<<Drop>>', lambda e: self._on_drop_audio(e, var, entry))

    def _bind_folder_drop(self, listbox, which):
        """Registra drag & drop en un Listbox (acepta carpetas y archivos de audio)."""
        if not _HAS_DND:
            return
        listbox.drop_target_register(DND_FILES)
        listbox.dnd_bind('<<DragEnter>>', lambda e: listbox.config(bg='#1a4a6e'))
        listbox.dnd_bind('<<DragLeave>>', lambda e: listbox.config(bg='#16213e'))
        listbox.dnd_bind('<<Drop>>', lambda e: self._on_drop_list(e, which, listbox))

    def _on_drop_list(self, event, which, listbox):
        """Procesa el drop en un Listbox: carpeta → carga todos los audios; archivo → agrega."""
        import re
        listbox.config(bg='#16213e')
        raw = event.data.strip()
        paths = [p[0] or p[1] for p in re.findall(r'\{([^}]+)\}|(\S+)', raw)]

        files_found = []
        for p in paths:
            p = p.replace('\\', '/')
            if os.path.isdir(p):
                for ext in self._AUDIO_EXTS:
                    files_found += glob.glob(os.path.join(p, ext))
            elif os.path.isfile(p) and any(
                    p.lower().endswith(e.replace('*', '')) for e in self._AUDIO_EXTS):
                files_found.append(p)

        if not files_found:
            messagebox.showinfo("Sin audio",
                                "No se encontraron archivos de audio en lo soltado.")
            return

        if which == 'voz':
            current = list(self.match_voz_files)
            for f in files_found:
                if f not in current: current.append(f)
            self._match_set_voz(sorted(current))
        else:
            current = list(self.match_beat_files)
            for f in files_found:
                if f not in current: current.append(f)
            self._match_set_beat(sorted(current))

    # ════════════════════════════════════════════════════════
    #  CLIPBOARD
    # ════════════════════════════════════════════════════════
    def _clipboard_loop(self):
        while True:
            try:
                text = self.root.clipboard_get()
                if text != self.last_clipboard:
                    self.last_clipboard = text
                    if 'tiktok.com/@' in text:
                        username = text.split('tiktok.com/@')[1].split('/')[0].split('?')[0]
                        if username and not any(a['username'].lower() == username.lower()
                                                for a in self.artists):
                            self.root.after(0, lambda u=username: self._ask_add(u))
            except: pass
            time.sleep(1.5)

    def _ask_add(self, username):
        if messagebox.askyesno("¿Agregar artista?",
                                f"Copiaste:\n@{username}\n\n¿Lo agrego al monitor?"):
            self.add_artist(username)

    def check_tutorial(self):
        if not getattr(self, 'has_seen_tutorial', False):
            ans = messagebox.askyesno("Bienvenido a TikTok Live Recorder",
                                      "¡Hola! Parece que es tu primera vez aquí.\n\n¿Sabes cómo usar este programa?")
            if ans:
                self.has_seen_tutorial = True
                self.save_config()
                self.show_tips()
            else:
                self.start_guided_tutorial()

    def show_tips(self):
        messagebox.showinfo("Tips Rápidos",
                            "Perfecto. Solo 3 recordatorios rápidos:\n\n"
                            "1. En el **Monitor**, los audios muy largos se cortarán automáticamente cada 30 min (puedes cambiarlo).\n"
                            "2. En el **Procesador**, usa 'Extraer Voz' para quitar los silencios y limpiar el audio.\n"
                            "3. En el **Emparejador Pro**, puedes hacer ZOOM arrastrando el mouse en las ondas para encajar la voz y el beat con precisión milimétrica.\n\n"
                            "¡A darle play y crear buena música!")

    def start_guided_tutorial(self):
        messagebox.showinfo("Paso 1: El Monitor Lives (El Cazador)",
                            "Este programa funciona como tu estudio de grabación y mezcla personal, dividido en 3 pestañas principales.\n\n"
                            "Primero estamos en **Monitor Lives**.\n\n"
                            "Aquí escribes el usuario de TikTok del artista que quieres grabar (o pegas su link) y le das a '+ Agregar'.\n\n"
                            "El programa vigilará en silencio si está en directo. Cuando cante, dale al botón verde '⏺ Grabar' y luego '⏹ Cortar' cuando termine. ¡Te guardará el MP3 en tu carpeta sin que tengas que gastar todo tu internet!")
                            
        messagebox.showinfo("Paso 2: Procesar Audio (La Limpieza)",
                            "Una vez tengas el audio guardado, vamos a la segunda pestaña: **Procesar Audio**.\n\n"
                            "A veces los artistas hablan mucho y cantan poco.\n"
                            "Aquí seleccionas el MP3 que grabaste, y el programa usará Inteligencia Artificial para:\n"
                            "1. Borrar todos los espacios donde no hay nadie hablando/cantando.\n"
                            "2. Extraer SOLAMENTE su voz, borrando ruidos y la música de fondo que tuviera el live.\n\n"
                            "El resultado será una voz Acapella limpia y lista para usar.")
                            
        messagebox.showinfo("Paso 3: Emparejador Pro (El Estudio)",
                            "Finalmente, la magia pura está en el **Emparejador Pro**.\n\n"
                            "1. Arriba cargas la voz acapella limpia y un Beat (pista musical) que tengas.\n"
                            "2. Puedes mover la voz hacia la izquierda o derecha para que encaje perfecto con el ritmo del beat (¡Arrastra el mouse en la gráfica para hacer Zoom!).\n"
                            "3. Abajo verás opciones profesionales: Puedes cambiarle el volumen a cada pista o usar '🎙️ Efecto Clon (Coros)' para que la voz suene doble como en un estudio real.\n\n"
                            "Cuando te guste cómo suena, dale a '💾 Exportar Mix Final'.")
                            
        messagebox.showinfo("¡Todo Listo!",
                            "¡Eso es todo!\n\n"
                            "Ya puedes cazar a tus artistas favoritos, limpiar sus voces y mezclarlas con los mejores beats.\n\n"
                            "Si alguna vez olvidas algo, lee la pestaña de Monitor Lives. ¡Que disfrutes creando tu música!")
        self.has_seen_tutorial = True
        self.save_config()

    # ════════════════════════════════════════════════════════
    #  CONFIG
    # ════════════════════════════════════════════════════════
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.artists       = data.get('artists', [])
                self.output_folder = data.get('output_folder', self.output_folder)
                if 'match_voz_folder' in data: self.match_voz_folder.set(data['match_voz_folder'])
                if 'match_beat_folder' in data: self.match_beat_folder.set(data['match_beat_folder'])
                if 'match_out_folder' in data: self.match_out_folder.set(data['match_out_folder'])
                
                if not hasattr(self, 'auto_cut_mins'): self.auto_cut_mins = tk.IntVar(value=30)
                if 'auto_cut_mins' in data: self.auto_cut_mins.set(data['auto_cut_mins'])
                self.has_seen_tutorial = data.get('has_seen_tutorial', False)
                
                for a in self.artists:
                    a['status'] = 'offline'; a['recording'] = False
                    a.setdefault('auto_record', True)
                # Perfil de artista
                self.artist_name.set(data.get('artist_name', ''))
                self.artist_genre.set(data.get('artist_genre', 'Hip-Hop / Rap'))
            except: pass

    def save_config(self):
        artists_to_save = [{**a, 'status': 'offline', 'recording': False} for a in self.artists]
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'artists':       artists_to_save,
                'output_folder': self.output_folder,
                'match_voz_folder': self.match_voz_folder.get(),
                'match_beat_folder': self.match_beat_folder.get(),
                'match_out_folder': self.match_out_folder.get(),
                'auto_cut_mins': self.auto_cut_mins.get() if hasattr(self, 'auto_cut_mins') else 30,
                'has_seen_tutorial': self.has_seen_tutorial,
                'artist_name':   self.artist_name.get(),
                'artist_genre':  self.artist_genre.get(),
            }, f, indent=2, ensure_ascii=False)

    def _on_close(self):
        """Cierre controlado: detiene grabaciones/procesos activos, guarda config y cierra."""
        # Señalizar a los threads que deben detenerse
        self.proc_running  = False
        self.match_running = False
        # Detener grabaciones activas
        for a in self.artists:
            a['recording'] = False
        try:
            self.save_config()
        except Exception:
            pass
        self.root.destroy()


# ── Entry point ─────────────────────────────────────────────
if __name__ == '__main__':
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    App(root)
    root.mainloop()
