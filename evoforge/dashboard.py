from .core.checkpoints import safe_load
"""Standard-library terminal UI; trainer runs in a separate child process."""
import csv
import curses
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import shutil


def _lines(path, limit=24):
    try:
        return path.read_text(errors='replace').splitlines()[-limit:]
    except FileNotFoundError:
        return []


def _metric(path):
    try:
        with path.open(newline='') as stream:
            values = list(csv.DictReader(stream))
        return values[-1] if values else None
    except (OSError, ValueError):
        return None


def _safe_add(scr, row, col, message, attr=0):
    h,w = scr.getmaxyx()
    if 0 <= row < h and 0 <= col < w:
        try:
            scr.addnstr(row,col,str(message), max(0,w-col-1),attr)
        except curses.error:
            pass


def _history(path):
    try:
        with path.open(newline='') as stream:
            return list(csv.DictReader(stream))
    except (OSError, ValueError):
        return []


def _spark(values, length=48):
    if not values:return '(no data)'
    values=values[-length:]
    lo,hi=min(values),max(values)
    chars='▁▂▃▄▅▆▇█'
    return ''.join(chars[min(7,int((v-lo)/(hi-lo)*7))] if hi!=lo else chars[3] for v in values)


def _latest_timing(directory):
    for line in reversed(_lines(directory/'timings.jsonl',1)):
        try:return json.loads(line)
        except (ValueError,TypeError):pass
    return None


SETTINGS_FIELDS = [
    ('game','Game','choice',['snake','flappy']),
    ('mode','Training mode','choice',['evolution','hybrid','ppo']),
    ('population','Population','int',(2,4096,1)),
    ('generations','Generations','int',(1,1000000,10)),
    ('elites','Elite agents','int',(1,4095,1)),
    ('ppo_candidates','PPO candidates','int',(0,4096,1)),
    ('ppo_episodes','PPO episodes','int',(1,10000,1)),
    ('eval_episodes','Evaluation episodes','int',(1,10000,1)),
    ('size','Board size','int',(5,128,1)),
    ('max_steps','Maximum steps','int',(1,100000,25)),
    ('seed','Random seed','int',(0,2147483647,1)),
    ('hidden','Hidden neurons','int',(8,2048,8)),
]


def _settings_defaults():
    from dataclasses import asdict
    from .trainer import Config
    return asdict(Config())


def _change_setting(settings, key, direction):
    item=next(row for row in SETTINGS_FIELDS if row[0]==key)
    if item[2]=='choice':
        choices=item[3];settings[key]=choices[(choices.index(settings[key])+direction)%len(choices)]
    else:
        lo,hi,step=item[3]
        settings[key]=max(lo,min(hi,int(settings[key])+direction*step))


def _validate_settings(settings):
    from .trainer import Config
    cfg=Config(**settings);cfg.validate()
    if cfg.elites >= cfg.population:
        raise ValueError('Elite agents must be fewer than population')
    if cfg.ppo_candidates>cfg.population:
        raise ValueError('PPO candidates cannot exceed population')
    if cfg.size<5:
        raise ValueError('Board size must be at least 5')
    return cfg


def _edit_settings(screen, directory):
    if (directory/'checkpoint.pt').exists():
        return 'Existing checkpoint: use E to extend generations; start a new run to change other settings.'
    path=directory/'config.json'
    try:
        settings=_settings_defaults()
        if path.exists():settings.update(json.loads(path.read_text()))
    except (OSError,ValueError,TypeError) as exc:
        return f'Cannot load settings: {exc}'
    selected=0;offset=0;message='Arrows navigate · Left/Right adjust · Enter edit · Click select · S save · Esc cancel'
    screen.timeout(100)
    while True:
        screen.erase();height,width=screen.getmaxyx()
        visible=max(1,height-10)
        offset=min(max(0,selected-visible+1),offset) if selected>=offset+visible else min(offset,selected)
        _safe_add(screen,1,3,'EVOFORGE  /  EXPERIMENT SETTINGS',curses.A_BOLD)
        _safe_add(screen,2,3,'Interactive configuration · changes are not applied until saved')
        _safe_add(screen,4,3,'PARAMETER',curses.A_BOLD)
        _safe_add(screen,4,max(23,width//2),'VALUE',curses.A_BOLD)
        for pos in range(offset,min(len(SETTINGS_FIELDS),offset+visible)):
            key,label,kind,_=SETTINGS_FIELDS[pos]
            row=5+pos-offset;selected_attr=curses.A_REVERSE if pos==selected else 0
            _safe_add(screen,row,3,('▶ ' if pos==selected else '  ')+label,selected_attr)
            value=('◀ '+str(settings[key])+' ▶') if kind=='choice' else str(settings[key])+'  (-/+)' 
            _safe_add(screen,row,max(23,width//2),value,selected_attr)
        _safe_add(screen,max(0,height-4),3,'↑↓ select    ←→ adjust    Enter edit    Mouse select/adjust')
        _safe_add(screen,max(0,height-3),3,'S save    Esc cancel    Home/End jump')
        _safe_add(screen,max(0,height-2),3,message[:max(1,width-6)])
        screen.refresh()
        key=screen.getch()
        if key==-1:continue
        if key in (27,ord('q'),ord('Q')):return 'Settings changes discarded.'
        if key in (curses.KEY_UP,ord('k')):selected=max(0,selected-1)
        elif key in (curses.KEY_DOWN,ord('j')):selected=min(len(SETTINGS_FIELDS)-1,selected+1)
        elif key==curses.KEY_HOME:selected=0
        elif key==curses.KEY_END:selected=len(SETTINGS_FIELDS)-1
        elif key in (curses.KEY_LEFT,ord('-'),ord('h')):_change_setting(settings,SETTINGS_FIELDS[selected][0],-1)
        elif key in (curses.KEY_RIGHT,ord('+'),ord('l')):_change_setting(settings,SETTINGS_FIELDS[selected][0],1)
        elif key==curses.KEY_MOUSE:
            try:
                _,mx,my,_,state=curses.getmouse()
                if state & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                    if 5<=my<5+visible and my-5+offset<len(SETTINGS_FIELDS):
                        selected=my-5+offset
                        if mx>=max(23,width//2):_change_setting(settings,SETTINGS_FIELDS[selected][0],1)
            except curses.error:pass
        elif key in (10,13,curses.KEY_ENTER):
            k,label,kind,_=SETTINGS_FIELDS[selected]
            if kind=='choice':_change_setting(settings,k,1)
            else:
                _safe_add(screen,max(0,height-2),3,f'Enter {label}: '.ljust(max(0,width-5)))
                screen.refresh();curses.echo();curses.curs_set(1);screen.timeout(-1)
                try:
                    raw=screen.getstr(max(0,height-2),min(width-2,4+len(label)+8),18).decode().strip()
                    if raw:settings[k]=int(raw)
                    message='Value updated; press S to validate and save.'
                except (ValueError,UnicodeDecodeError):message='Invalid integer; previous value retained.'
                finally:curses.noecho();curses.curs_set(0);screen.timeout(100)
        elif key in (ord('s'),ord('S')):
            try:
                _validate_settings(settings)
                directory.mkdir(parents=True,exist_ok=True)
                tmp=path.with_suffix('.json.tmp');tmp.write_text(json.dumps(settings,indent=2));tmp.replace(path)
                return 'Settings saved. Press S to start training.'
            except (ValueError,TypeError,OSError) as exc:message=f'Cannot save: {exc}'


def _extend(screen, directory):
    checkpoint=directory/'checkpoint.pt'
    if not checkpoint.exists():
        return 'No checkpoint to extend; configure a new run first.'
    import torch
    try:
        saved=safe_load(checkpoint)
        cfg=dict(saved['config'])
        current=max(int(cfg['generations']),int(saved['generation']))
        curses.echo();curses.curs_set(1);screen.nodelay(False)
        screen.erase()
        _safe_add(screen,2,2,f'Completed {saved["generation"]} generations. Current target {current}.')
        _safe_add(screen,4,2,'Add how many generations? (e.g. 100): ')
        screen.refresh()
        raw=screen.getstr(4,43,12).decode().strip()
        if not raw:return 'Extension canceled.'
        extra=int(raw)
        if extra<1 or extra>1000000:return 'Enter a positive number up to 1000000.'
        cfg['generations']=current+extra
        (directory/'config.json').write_text(json.dumps(cfg,indent=2))
        return f'Extended run to {cfg["generations"]} generations. Press S to resume.'
    except (OSError,ValueError,KeyError,RuntimeError) as exc:
        return f'Extension failed: {exc}'
    finally:
        curses.noecho();curses.curs_set(0);screen.nodelay(True)


def _command(directory, resume):
    cfgfile = directory/'config.json'
    if cfgfile.exists():
        config=json.loads(cfgfile.read_text())
        flags=[]
        for key in ('game','mode','population','generations','elites','ppo_candidates','ppo_episodes',
                    'eval_episodes','size','max_steps','seed','hidden'):
            flags += ['--'+key.replace('_','-'), str(config.get(key,'snake') if key=='game' else config[key])]
    else:
        flags=['--mode','hybrid','--population','24','--generations','30',
               '--ppo-candidates','3','--output',str(directory)]
    if '--output' not in flags:
        flags += ['--output',str(directory)]
    if resume:
        flags += ['--resume']
    return [sys.executable,'-m','evoforge.cli','train',*flags]


def launch(directory):
    if (directory/'checkpoint.pt').exists():
        return _command(directory,True)
    return _command(directory,False)


def run(screen, directory):
    curses.curs_set(0)
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.mouseinterval(0)
    except curses.error:
        pass
    screen.nodelay(True)
    screen.timeout(200)
    proc=None
    viewer=None
    log_handle=None
    show_logs=False
    show_graph=False
    inspector=None
    paused=False
    status='Press S to start training.'
    directory.mkdir(parents=True,exist_ok=True)
    logfile=directory/'training.log'
    viewerlog=directory/'viewer.log'
    try:
        while True:
            screen.erase()
            h,w=screen.getmaxyx()
            if inspector is not None:
                inspector.tick()
                inspector.render(screen,_safe_add)
                screen.refresh()
                key=screen.getch()
                if key in (ord("b"),ord("B"),ord("v"),ord("V")):
                    inspector=None
                elif key in (ord("q"),ord("Q")):
                    inspector=None
                    status="Returned to dashboard. Press Q again to quit."
                elif key != -1:
                    inspector.handle(key)
                continue
            _safe_add(screen,0,2,'╭─ EVOFORGE ─────────────────────────────  EXPERIMENT CONTROL CENTER ─╮', curses.A_BOLD)
            _safe_add(screen,1,2,' S Start   P Pause   V Spectator   G Analytics   L Logs   C Settings   E Extend   Q Exit')
            _safe_add(screen,2,2,'Experiment  /  '+str(directory))
            try:
                from .games import game_spec
                selected_game=json.loads((directory/'config.json').read_text()).get('game','snake')
                score_label=game_spec(selected_game).score_label.title()
            except (OSError,ValueError,KeyError):
                score_label='Score'
            if proc is not None and proc.poll() is not None:
                status=f'Training stopped (exit {proc.returncode}).'
                proc=None
                if log_handle:
                    log_handle.close();log_handle=None
            state=('Paused' if paused else 'Running') if proc else 'Idle'
            _safe_add(screen,4,2,f'● {state.upper()}  │  {status}',curses.A_BOLD)
            metric=_metric(directory/'metrics.csv')
            if metric:
                _safe_add(screen,6,2,'Most recent completed generation: '+str(metric.get('generation','?')))
                _safe_add(screen,7,2,'Best train fitness: '+str(metric.get('best_train','?')))
                _safe_add(screen,8,2,'Mean train fitness: '+str(metric.get('mean_train','?')))
                _safe_add(screen,9,2,'Hall of fame fitness: '+str(metric.get('hall_of_fame','?')))
                _safe_add(screen,10,2,f'{score_label} (top / validation): '+str(metric.get('best_food','?'))+' / '+str(metric.get('validation_food','?')))
            else:
                _safe_add(screen,6,2,'No generation results yet.')
            timing=_latest_timing(directory)
            if timing:
                _safe_add(screen,11,2,f"Timing: evaluate {timing['evaluation_seconds']:.2f}s | total {timing['total_seconds']:.2f}s")
            if show_graph:
                rows=_history(directory/'metrics.csv')
                _safe_add(screen,12,2,'FITNESS HISTORY (best train / mean train):',curses.A_BOLD)
                for row,field in [(14,'best_train'),(16,'mean_train')]:
                    try: vals=[float(v[field]) for v in rows]
                    except (ValueError,KeyError):vals=[]
                    _safe_add(screen,row,2,field+': '+_spark(vals,max(8,min(w-24,70))))
            elif show_logs:
                _safe_add(screen,11,2,'RAW TRAINER OUTPUT (last lines):',curses.A_BOLD)
                lines=_lines(logfile,max(1,h-14))
                for i,line in enumerate(lines):
                    _safe_add(screen,12+i,2,line)
            else:
                _safe_add(screen,11,2,'LATEST LOGS  (L expands raw output)',curses.A_BOLD)
                for i,line in enumerate(_lines(logfile,max(1,min(6,h-14)))):
                    _safe_add(screen,12+i,2,line)
                _safe_add(screen,max(0,h-3),2,'Press V for the terminal game inspector (no display forwarding).')
            screen.refresh()
            key=screen.getch()
            if key==curses.KEY_MOUSE:
                try:
                    _,mx,my,_,button=curses.getmouse()
                    if my==1 and button & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                        for x1,x2,shortcut in [(2,12,ord('s')),(12,22,ord('p')),(22,36,ord('v')),(36,50,ord('g')),(50,59,ord('l')),(59,72,ord('c')),(72,83,ord('e')),(83,100,ord('q'))]:
                            if x1<=mx<x2:key=shortcut;break
                except curses.error:pass
            if key in (ord('q'),ord('Q')):
                if proc and proc.poll() is None:
                    status='Stop training before closing the dashboard? Y confirms; N returns.'
                    screen.nodelay(False)
                    _safe_add(screen,h-1,2,status)
                    screen.refresh()
                    answer=screen.getch()
                    screen.nodelay(True)
                    if answer not in (ord('y'),ord('Y')):
                        continue
                    if paused and os.name=='posix':
                        proc.send_signal(__import__('signal').SIGCONT)
                    proc.terminate()
                    try:proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                break
            if key in (ord('l'),ord('L')):
                show_logs=not show_logs;show_graph=False
            if key in (ord('g'),ord('G')):
                show_graph=not show_graph;show_logs=False
            if key in (ord('c'),ord('C')):
                if proc and proc.poll() is None:status='Stop training before changing settings.'
                else:status=_edit_settings(screen,directory)
            if key in (ord('e'),ord('E')):
                if proc and proc.poll() is None:
                    status='Stop training before extending.'
                else:
                    status=_extend(screen,directory)
            if key in (ord('s'),ord('S')):
                if proc and proc.poll() is None:
                    status='Training is already running.'
                else:
                    try:
                        command=launch(directory)
                        log_handle=logfile.open('a',buffering=1)
                        log_handle.write('\n=== Starting: '+ ' '.join(command)+' ===\n')
                        # A fresh session keeps the worker alive when an SSH shell disconnects.
                        proc=subprocess.Popen(command,stdout=log_handle,stderr=subprocess.STDOUT,start_new_session=True)
                        paused=False
                        status=f'Started process {proc.pid}.'
                    except Exception as exc:
                        status=f'Cannot launch: {exc}'
            if key in (ord('p'),ord('P')):
                if not proc:
                    status='No active training process.'
                elif os.name != 'posix':
                    status='Pause is currently supported only on POSIX systems.'
                else:
                    import signal
                    paused=not paused
                    proc.send_signal(signal.SIGSTOP if paused else signal.SIGCONT)
                    status='Paused training.' if paused else 'Resumed training.'
            if key in (ord('v'),ord('V')):
                from .terminal_viewer import TerminalInspector
                inspector = TerminalInspector(directory)
    finally:
        if log_handle:
            log_handle.close()


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description='EvoForge terminal dashboard')
    p.add_argument('--output',default='runs/hybrid')
    args=p.parse_args(argv)
    curses.wrapper(run,Path(args.output))


if __name__=='__main__':
    main()
