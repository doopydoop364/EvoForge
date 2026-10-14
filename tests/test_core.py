import numpy as np
import torch
from evoforge.snake import Snake
from evoforge.policy import Policy
from evoforge.algorithms import mutate,crossover,evaluate,ppo_refine
from evoforge.trainer import Config,Trainer

def test_snake_seed_and_terminal():
    a,b=Snake(size=6,max_steps=15),Snake(size=6,max_steps=15)
    assert np.array_equal(a.reset(123),b.reset(123))
    for action in [1,1,1,1,1,1,1]:
        if a.done:break
        x,r,d,info=a.step(action)
        y,r2,d2,info2=b.step(action)
        assert np.array_equal(x,y) and r==r2 and d==d2
    assert a.done

def test_genetic_and_ppo():
    torch.manual_seed(7)
    agent=Policy(hidden=8)
    rng=np.random.default_rng(7)
    child=mutate(agent,rng,probability=1)
    assert any(not torch.equal(x,y) for x,y in zip(agent.parameters(),child.parameters()))
    mixed=crossover(agent,child,rng)
    assert mixed.act(Snake().reset(1),True) in (0,1,2)
    original=[v.detach().clone() for v in agent.parameters()]
    updated=ppo_refine(agent,seed=7,episodes=2,size=6,max_steps=20,epochs=1)
    assert all(torch.equal(x,y) for x,y in zip(agent.parameters(),original))
    assert all(torch.isfinite(x).all() for x in updated.parameters())
    assert np.isfinite(evaluate(updated,[1,2],size=6,max_steps=20))

def test_resume(tmp_path):
    cfg=Config(mode='evolution',population=4,elites=1,generations=1,
               eval_episodes=1,size=6,max_steps=12,hidden=8)
    t=Trainer(cfg,tmp_path);t.run()
    assert (tmp_path/'champion.pt').exists()
    cfg.generations=2
    second=Trainer(cfg,tmp_path,resume=True)
    assert second.generation==1
    second.run()
    assert second.generation==2

def test_food_statistics_and_observation():
    from evoforge.algorithms import food_stats
    env=Snake(size=8,max_steps=30)
    obs=env.reset(321)
    assert obs.shape == (17,)
    assert np.all(np.isfinite(obs))
    model=Policy(hidden=8)
    assert np.isfinite(food_stats(model,[1,2],8,30))


def test_resume_extension_and_metrics(tmp_path):
    import csv
    cfg=Config(mode='evolution',population=4,elites=1,generations=1,
               eval_episodes=1,size=6,max_steps=12,hidden=8)
    Trainer(cfg,tmp_path).run()
    cfg.generations=3
    resumed=Trainer(cfg,tmp_path,resume=True)
    resumed.run()
    assert resumed.generation==3
    with (tmp_path/'metrics.csv').open() as stream:
        rows=list(csv.DictReader(stream))
    assert len(rows)==3
    assert 'best_food' in rows[-1]
    assert 'validation_food' in rows[-1]
