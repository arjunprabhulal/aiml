import json
from pathlib import Path
import subprocess
import sys
import pytest
from pydantic import ValidationError
from split_models import SplitCase,SplitDataset,freeze
from tracker_leakcheck import assign_groups,check,word_similarity
ROOT=Path(__file__).parent

def case(id,issue,split='development',source_id=None,label='bug'):
    return SplitCase(id=id,issue=issue,split=split,source_id=source_id,expected={'label':label})
def dataset(*cases):return SplitDataset(name='tracker',version=1,cases=list(cases))

def test_group_split_keeps_each_variant_with_its_source():
    data=SplitDataset.model_validate_json((ROOT/'tracker-splits.json').read_text())
    by={c.id:c for c in data.cases}
    assert all(c.split==by[c.source_id].split for c in data.cases if c.source_id)
    assert check(data)['decision']=='pass'

def test_group_assignment_repeats_with_the_same_seed():
    rows=[case(str(i),'Issue '+str(i)).model_dump(exclude={'split'}) for i in range(12)]
    assert assign_groups(rows)==assign_groups(rows)

def test_an_identical_input_in_both_splits_blocks():
    run=check(dataset(case('dev','tracker sync crashes'),case('held','TRACKER sync crashes!','held_out')))
    assert run['decision']=='block'
    assert run['findings'][0]['check']=='duplicate input'

def test_near_duplicate_is_review_instead_of_a_leakage_verdict():
    left='tracker sync reads task database after every edit'
    right='tracker sync writes task database after every edit'
    assert .6<=word_similarity(left,right)<1
    run=check(dataset(case('dev',left),case('held',right,'held_out',label='feature')))
    assert run['decision']=='review'
    assert all(f['severity']=='review' for f in run['findings'])

def test_lexical_checks_do_not_find_every_semantic_paraphrase():
    run=check(dataset(case('dev','Where does tracker store its database on disk?'),
                     case('held','Which file contains my saved tasks?','held_out')))
    assert run['findings']==[]  # Known blind spot; not a passing semantic leakage test.

def test_a_known_source_crossing_the_split_blocks_even_with_different_words():
    run=check(dataset(case('original','tracker crashes on startup'),
                     case('variant','The application fails before opening its window','held_out','original')))
    assert any(f['check']=='source crosses split' for f in run['findings'])
    assert run['decision']=='block'

def test_a_changed_expected_label_invalidates_the_frozen_split():
    original=dataset(case('held','tracker crashes on startup','held_out'))
    locked=freeze(original);changed=original.model_copy(deep=True);changed.cases[0].expected.label='feature'
    assert check(changed,locked=locked)['findings'][0]['reason']=='edited'

@pytest.mark.parametrize('change,reason',[('remove','removed'),('move','moved'),('add','added')])
def test_frozen_membership_changes_are_reported(change,reason):
    original=dataset(case('dev','Please support task reminders'),case('held','tracker crashes on startup','held_out'))
    locked=freeze(original);changed=original.model_copy(deep=True)
    if change=='remove':changed.cases.pop()
    elif change=='move':changed.cases[-1].split='development'
    else:changed.cases.append(case('new','Explain the configuration keys','held_out'))
    assert any(f.get('reason')==reason for f in check(changed,locked=locked)['findings'])

def test_a_lock_from_another_dataset_is_refused():
    data=dataset(case('held','tracker crashes on startup','held_out'));locked=freeze(data);locked.dataset_name='other'
    with pytest.raises(ValueError,match='another dataset'):check(data,locked=locked)

def test_a_held_out_excerpt_in_the_prompt_needs_review():
    text='tracker sync writes task database after every edit and reports its revision'
    run=check(dataset(case('held',text,'held_out')),prompt='Follow these examples:\n'+text)
    assert run['decision']=='review';assert run['findings'][0]['check']=='held-out excerpt in prompt'

@pytest.mark.parametrize('issue',['','   ','!!!'])
def test_blank_issue_is_refused_before_tokenization(issue):
    with pytest.raises(ValidationError):case('empty',issue)

def test_a_variant_must_name_a_real_original_case():
    with pytest.raises(ValidationError,match='original case'):
        dataset(case('variant','Text here','held_out','missing'))

def test_saved_scenarios_reproduce_without_model_calls():
    result=subprocess.run([sys.executable,'record_tracker_splits.py','--check'],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
