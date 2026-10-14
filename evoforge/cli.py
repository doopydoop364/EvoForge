from .core.checkpoints import safe_load
import argparse
import json
from pathlib import Path
import torch
from .games import make_env, game_spec
from .policy import Policy
from .trainer import Trainer,Config

def main():
    parser=argparse.ArgumentParser(description='EvoForge research MVP')
    sub=parser.add_subparsers(dest='command',required=True)
    games=sub.add_parser('games',help='inspect installed game plugins')
    games.add_argument('action',choices=['list','inspect','validate'])
    games.add_argument('game_id',nargs='?')
    train=sub.add_parser('train',help='run or resume experiment')
    for flag,kwargs in {
        'mode':dict(choices=['evolution','hybrid','ppo'],default='hybrid'),
        'game':dict(default='snake'),
        'population':dict(type=int,default=24),'generations':dict(type=int,default=20),
        'elites':dict(type=int,default=2),'ppo-candidates':dict(type=int,default=3),
        'ppo-episodes':dict(type=int,default=4),'eval-episodes':dict(type=int,default=3),
        'size':dict(type=int,default=10),'max-steps':dict(type=int,default=300),
        'seed':dict(type=int,default=42),'hidden':dict(type=int,default=64),
    }.items():train.add_argument('--'+flag,**kwargs)
    train.add_argument('--output',default='runs/snake-hybrid')
    train.add_argument('--resume',action='store_true')
    play=sub.add_parser('play',help='render a saved champion in the terminal')
    play.add_argument('checkpoint');play.add_argument('--seed',type=int,default=123)
    dash=sub.add_parser('dashboard',help='interactive terminal control center')
    dash.add_argument('--output',default='runs/hybrid')
    tui=sub.add_parser('tui',help='Textual terminal app (install the tui extra)')
    tui.add_argument('--output',default='runs/hybrid')
    args=parser.parse_args(['dashboard'] if len(__import__('sys').argv)==1 else None)
    if args.command=='games':
        from dataclasses import asdict
        from .games import available_games
        from .sdk import validate_game
        from .sdk.registry import ERRORS
        if args.action=='list':
            print(json.dumps({'games':available_games(),'errors':ERRORS},indent=2))
        elif not args.game_id:
            parser.error('game id required')
        elif args.action=='validate':
            print(json.dumps(validate_game(args.game_id),indent=2))
        else:
            spec=game_spec(args.game_id)
            print(json.dumps({k:v for k,v in asdict(spec).items() if k!='environment'},indent=2))
    elif args.command=='tui':
        try:
            from .tui import main as tui_main
        except ImportError:
            parser.error('Textual not installed. Install the tui extra or use dashboard.')
        tui_main(args.output)
    elif args.command=='dashboard':
        from .dashboard import main as dashboard_main
        dashboard_main(['--output',args.output])
    elif args.command=='train':
        cfg=Config(**{key.replace('-','_'):getattr(args,key.replace('-','_')) for key in
                 ('mode','game','population','generations','elites','ppo-candidates','ppo-episodes',
                  'eval-episodes','size','max-steps','seed','hidden')})
        Trainer(cfg,args.output,resume=args.resume).run()
    elif args.command=='play':
        data=safe_load(args.checkpoint)
        cfg=data['config'];model=Policy(hidden=cfg['hidden']);model.load_state_dict(data['state_dict'])
        env=make_env(cfg.get('game','snake'),cfg['size'],cfg['max_steps']);obs=env.reset(args.seed);done=False
        while not done:
            obs,_,done,info=env.step(model.act(obs,deterministic=True))
            print('\033[2J\033[H'+env.render()+'\n'+json.dumps(info),flush=True)
        print('Finished:',info)

if __name__=='__main__':main()
