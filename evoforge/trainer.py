"""Repeatable experiment runner, checkpoints and champion exports."""
from dataclasses import asdict, dataclass
from pathlib import Path
import csv
import json
import random
import time
import os
import numpy as np
import torch
from .policy import Policy
from .games import game_spec
from .algorithms import evaluate, mutate, crossover, ppo_refine

@dataclass
class Config:
    mode: str = 'hybrid'
    game: str = 'snake'
    population: int = 24
    generations: int = 20
    elites: int = 2
    ppo_candidates: int = 3
    ppo_episodes: int = 4
    eval_episodes: int = 3
    size: int = 10
    max_steps: int = 300
    seed: int = 42
    mutation_probability: float = 0.05
    mutation_sigma: float = 0.08
    hidden: int = 64
    def validate(self):
        game_spec(self.game)
        if self.mode not in ('evolution','hybrid','ppo'):
            raise ValueError('mode must be evolution, hybrid or ppo')
        if self.population < 2 or not 1 <= self.elites < self.population:
            raise ValueError('need population>=2 and 1<=elites<population')
        if self.generations<1 or self.eval_episodes<1 or self.ppo_episodes<1:
            raise ValueError('episode and generation counts must be positive')
        if not 0 <= self.ppo_candidates <= self.population:
            raise ValueError('invalid ppo_candidates')
        if not (0 <= self.mutation_probability <= 1) or self.mutation_sigma < 0:
            raise ValueError('invalid mutation settings')

class Trainer:
    def __init__(self, config, directory, resume=False):
        self.cfg=config
        self.cfg.validate()
        self.dir=Path(directory);self.dir.mkdir(parents=True,exist_ok=True)
        self.checkpoint=self.dir/'checkpoint.pt'
        self.rng=np.random.default_rng(config.seed)
        torch.manual_seed(config.seed);random.seed(config.seed)
        self.generation=0
        self.checkpoint_recovered=False
        self.population=[Policy(hidden=config.hidden) for _ in range(config.population)]
        self.champion_score=float('-inf')
        self.champion=None
        if resume:
            self._load()
        (self.dir/'config.json').write_text(json.dumps(asdict(self.cfg),indent=2))

    def _save(self):
        payload={'config':asdict(self.cfg),'generation':self.generation,
                 'population':[m.state_dict() for m in self.population],
                 'champion':self.champion.state_dict() if self.champion else None,
                 'champion_score':self.champion_score,'numpy_state':self.rng.bit_generator.state,
                 'torch_state':torch.get_rng_state(),'python_state':random.getstate()}
        temp=self.checkpoint.with_suffix('.tmp')
        torch.save(payload,temp)
        # Keep one known-good generation for recovery from interrupted/corrupt writes.
        backup=self.checkpoint.with_suffix('.pt.bak')
        if self.checkpoint.exists():
            backup_tmp=backup.with_suffix('.tmp')
            backup_tmp.write_bytes(self.checkpoint.read_bytes());backup_tmp.replace(backup)
        temp.replace(self.checkpoint)

    def _load(self):
        try:
            data=torch.load(self.checkpoint,map_location='cpu',weights_only=False)
        except Exception:
            backup=self.checkpoint.with_suffix('.pt.bak')
            if not backup.exists(): raise
            data=torch.load(backup,map_location='cpu',weights_only=False)
            self.checkpoint_recovered=True
        if len(data['population']) != len(self.population):
            raise ValueError('checkpoint population count does not match configuration')
        old_config = dict(data['config'])
        old_config.setdefault('game','snake')
        if old_config != asdict(self.cfg):
            # Allow users to extend total generations without changing training settings.
            previous=old_config;current=asdict(self.cfg)
            previous.pop('generations');current.pop('generations')
            if previous != current:
                raise ValueError('resume config differs from checkpoint')
        self.generation=data['generation']
        for model,state in zip(self.population,data['population']):model.load_state_dict(state)
        self.champion_score=data['champion_score']
        if data['champion'] is not None:
            self.champion=Policy(hidden=self.cfg.hidden)
            self.champion.load_state_dict(data['champion'])
        self.rng.bit_generator.state=data['numpy_state']
        torch.set_rng_state(data['torch_state']);random.setstate(data['python_state'])

    def _append_metric(self,record):
        path=self.dir/'metrics.csv'
        existing=[]; fields=[]
        if path.exists() and path.stat().st_size:
            with path.open(newline='') as source:
                reader=csv.DictReader(source); fields=list(reader.fieldnames or []); existing=list(reader)
        merged=fields+[key for key in record if key not in fields]
        if fields and merged != fields:
            temporary=path.with_suffix('.csv.tmp')
            with temporary.open('w',newline='') as target:
                writer=csv.DictWriter(target,fieldnames=merged);writer.writeheader();writer.writerows(existing);writer.writerow(record)
            temporary.replace(path)
        else:
            with path.open('a',newline='') as target:
                writer=csv.DictWriter(target,fieldnames=merged or list(record))
                if not fields:writer.writeheader()
                writer.writerow(record)

    def run(self):
        self._worker_status("running")
        for g in range(self.generation,self.cfg.generations):
            self._worker_status("running", generation=g)
            generation_started=time.perf_counter()
            # Common random numbers reduce evaluation noise within a generation.
            seeds=self.rng.integers(0,2**31,size=self.cfg.eval_episodes)
            scores=[evaluate(m,seeds,self.cfg.size,self.cfg.max_steps,game=self.cfg.game) for m in self.population]
            evaluation_seconds=time.perf_counter()-generation_started
            order=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)
            best=scores[order[0]]
            # A disjoint validation set is used for persistent champion selection.
            val_seeds=[self.cfg.seed+900000+i for i in range(12)]
            candidate=self.population[order[0]]
            candidate_validation=evaluate(candidate,val_seeds,self.cfg.size,self.cfg.max_steps,game=self.cfg.game)
            if candidate_validation>self.champion_score:
                self.champion=candidate.clone();self.champion_score=candidate_validation
                torch.save({'state_dict':self.champion.state_dict(),'config':asdict(self.cfg),
                            'validation_score':self.champion_score},self.dir/'champion.pt')
            # Food statistics are direct game outcomes, not shaped fitness.
            from .algorithms import food_stats
            food_best=food_stats(candidate,seeds,self.cfg.size,self.cfg.max_steps,game=self.cfg.game)
            food_val=food_stats(candidate,val_seeds,self.cfg.size,self.cfg.max_steps,game=self.cfg.game)
            record={'generation':g,'best_food':food_best,'validation_food':food_val,
                    'best_train':best,'mean_train':float(np.mean(scores)),
                    'best_validation':candidate_validation,'hall_of_fame':self.champion_score,
                    'median_train':float(np.median(scores)),
                    'std_train':float(np.std(scores)),
                    'fitness_gap':float(best-np.mean(scores)),
                    'population_diversity':float(np.mean([np.mean(np.abs(a-b)) for i,a in enumerate(scores) for b in scores[i+1:]])) if len(scores)>1 else 0.0}
            self._append_metric(record)
            print(json.dumps(record),flush=True)
            # Atomically publish a sample of policies for independent spectator replays.
            sample=[self.population[i].state_dict() for i in order[:min(9,len(order))]]
            viewfile=self.dir/"spectator.pt"
            tmp=viewfile.with_suffix(".tmp")
            torch.save({"config":asdict(self.cfg),"generation":g,"policies":sample},tmp)
            tmp.replace(viewfile)
            ppo_updates=0
            if self.cfg.mode=='ppo':
                # PPO-only baseline: multiple seeds of the same on-policy learner,
                # without selection, mutations or crossover.
                ppo_updates=len(self.population)
                self.population=[ppo_refine(m,int(self.rng.integers(2**31)),self.cfg.ppo_episodes,
                                            self.cfg.size,self.cfg.max_steps) for m in self.population]
            else:
                parents=[self.population[i] for i in order]
                nxt=[parents[i].clone() for i in range(self.cfg.elites)]
                if self.cfg.mode=='hybrid':
                    for i in range(min(self.cfg.ppo_candidates,len(parents))):
                        ppo_updates+=1
                        improved=ppo_refine(parents[i],int(self.rng.integers(2**31)),
                                           self.cfg.ppo_episodes,self.cfg.size,self.cfg.max_steps,game=self.cfg.game)
                        # PPO acceptance uses fresh random scenarios; never the training rollouts.
                        check=self.rng.integers(0,2**31,size=max(3,self.cfg.eval_episodes))
                        if evaluate(improved,check,self.cfg.size,self.cfg.max_steps,game=self.cfg.game)>=evaluate(parents[i],check,self.cfg.size,self.cfg.max_steps,game=self.cfg.game):
                            nxt.append(improved)
                pool=parents[:max(2,len(parents)//3)]
                while len(nxt)<self.cfg.population:
                    a=pool[int(self.rng.integers(len(pool)))]
                    if self.rng.random()<0.3:
                        b=pool[int(self.rng.integers(len(pool)))]
                        a=crossover(a,b,self.rng)
                    nxt.append(mutate(a,self.rng,self.cfg.mutation_probability,self.cfg.mutation_sigma))
                self.population=nxt[:self.cfg.population]
            self.generation=g+1
            self._save()
            timings={"generation":g,"evaluation_seconds":round(evaluation_seconds,3),"ppo_refinements":ppo_updates,"total_seconds":round(time.perf_counter()-generation_started,3)}
            with (self.dir/"timings.jsonl").open("a") as f:f.write(json.dumps(timings)+"\n")
        self._worker_status("complete", generation=self.generation)

    def _worker_status(self, state, generation=None):
        payload={"pid":os.getpid(),"state":state,"generation":self.generation if generation is None else generation,
                 "target_generations":self.cfg.generations,"updated_at":time.time()}
        target=self.dir/'worker.json'; temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload,indent=2));temporary.replace(target)
