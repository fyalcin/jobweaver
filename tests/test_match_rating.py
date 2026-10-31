"""Evidence rules, grounding and complete storage/API/automation integration. Fictional inputs only."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from jobweaver import analysis_validation as validation
from jobweaver import db
from jobweaver import scrapers
from jobweaver import server
from jobweaver.input_limits import validate_collection_config
from jobweaver.job_policy import (RATINGS, analysis_current, apply_rating, deduplicate_checks, fingerprint,
                        judgement_calls, match_rating, normalize_rating_config, qualifies, deduplicate_conflicts)


def checks(must='', nice=''):
    values = {'s': 'shown', 'r': 'related', 'm': 'missing'}
    return [dict(requirement=f'{kind} {i}', importance=kind, posting_quote=f'{kind} requirement {i}',
                 coverage=values[code], cv_quote='CV quote' if code != 'm' else '')
            for kind, codes in [('must', must), ('nice', nice)] for i, code in enumerate(codes)]


def conflict(name='Work model', severity='soft'):
    return dict(preference=name, notes_quote=f'I prefer {name}', posting_quote='On site', severity=severity)


class RatingRulesTest(unittest.TestCase):
    def test_table(self):
        cases = [('sss','','Great'), ('ssr','','Great'), ('srr','','Good'), ('sss','mm','Good'),
                 ('sss','sm','Great'), ('sssm','','Decent'), ('ssm','','Decent'), ('sm','','Stretch'),
                 ('ssmm','','Stretch'), ('smm','','Poor'), ('mmm','','Poor'), ('','sss','Good'),
                 ('','smm','Poor'), ('','','Unrated')]
        for must, nice, label in cases:
            with self.subTest(must=must, nice=nice):
                self.assertEqual(match_rating(checks(must,nice)), label)

    def test_conflicts_and_blockers(self):
        self.assertEqual(match_rating(checks('sss'), [conflict()]), 'Good')
        self.assertEqual(match_rating(checks('sss'), [conflict(), conflict('Travel')]), 'Decent')
        shared=dict(conflict('Travel'), notes_quote=conflict()['notes_quote'])
        self.assertEqual(match_rating(checks('sss'), [conflict(), shared]), 'Decent')
        self.assertEqual(match_rating(checks('mmm'), [conflict()]), 'Poor')
        self.assertEqual(match_rating(checks('sss'), [conflict(severity='hard')]), 'Blocked')
        self.assertEqual(match_rating(checks('sss'), eligibility_state='ineligible'), 'Blocked')
        self.assertEqual(match_rating(checks('sss'), eligibility_state='needs_review'), 'Great')

    def test_duplicates_cannot_inflate_or_demote(self):
        items = checks('ssm')
        self.assertEqual(match_rating(items + [items[0]] * 20), 'Decent')
        self.assertEqual(match_rating(checks('sss'), [conflict()] * 5), 'Good')
        duplicate = dict(items[0], coverage='missing', cv_quote='')
        self.assertEqual(match_rating(items + [duplicate]), 'Poor')
        self.assertEqual(match_rating([dict(items[0], requirement='Python', posting_quote='Python and SQL required'),
                                      dict(items[1], requirement='SQL', posting_quote='Python and SQL required'),
                                      items[2]]), 'Decent')
        self.assertEqual(len(deduplicate_checks(items + [dict(items[0], requirement=' MUST   0!')])), 3)

    def test_duplicate_stricter_evidence_is_retained_without_merging_language_names(self):
        optional=dict(checks('s')[0],requirement='Python',importance='nice',posting_quote='Python is a plus')
        firm=dict(optional,importance='must',posting_quote='Python is required')
        deduped=deduplicate_checks([optional,firm])
        self.assertEqual(deduped[0]['importance'],'must')
        self.assertEqual(deduped[0]['posting_quote'],'Python is required')
        languages=[dict(firm,requirement=name) for name in ('C','C++','C#')]
        self.assertEqual(len(deduplicate_checks(languages)),3)
        soft=conflict()
        hard=dict(soft,severity='hard',notes_quote='I will only work remotely')
        self.assertEqual(deduplicate_conflicts([soft,hard])[0]['notes_quote'],hard['notes_quote'])

    def test_judgement_calls(self):
        self.assertEqual(judgement_calls(checks('ssr')), [{'requirement': 'must 2', 'if_missing': 'Decent'}])
        self.assertEqual(judgement_calls(checks('smmmr')), [])
        self.assertEqual(judgement_calls(checks('ssr'), [conflict(severity='hard')]), [])

    def test_invalid_enums_rejected(self):
        for changes in ({'coverage':'maybe'}, {'importance':'critical'}):
            with self.assertRaises(ValueError):
                match_rating([dict(checks('s')[0], **changes)])
        with self.assertRaises(ValueError):
            match_rating(checks('s'), [conflict(severity='medium')])


class MatchGroundingTest(unittest.TestCase):
    def analyze(self, data, posting='Python required', cv='Python experience'):
        payload = {'german_level':'none', 'german_strength':'none', 'summary':'Fictional role',
                   'match_checks':[], **data}
        with patch('jobweaver.scrapers.run_ai_prompt', return_value=json.dumps(payload)) as model:
            result = scrapers.process_job_with_ai(posting, cv, model_name='mock', denoise=False)
        self.assertEqual(model.call_count, 1)
        return result

    def test_verified_quotes_and_cv_downgrade_are_persistable(self):
        item = dict(checks('s')[0], requirement='Python', posting_quote='Python required', cv_quote='Python experience')
        result = self.analyze({'match_checks':[item]})
        self.assertEqual(result['match_rating'], 'Great')
        self.assertEqual(result['grounding_status'], 'verified')
        result = self.analyze({'match_checks':[dict(item, cv_quote='Invented experience')]})
        self.assertEqual(result['match_rating'], 'Poor')
        self.assertEqual(result['match_checks'][0]['cv_quote'], '')
        self.assertEqual(result['grounding_status'], 'adjusted')
        self.assertEqual(result['grounding_issues'][0]['type'], 'ungrounded_cv_quote')
        self.assertNotIn('Invented experience', json.dumps(result))

    def test_ungrounded_missing_must_have_retries_then_fails_instead_of_disappearing(self):
        good = dict(checks('s')[0], posting_quote='Python required', cv_quote='Python experience')
        bad = dict(checks('m')[0], requirement='SQL', posting_quote='Invented SQL requirement')
        payload={'german_level':'none','summary':'Role','match_checks':[good,bad]}
        with patch('jobweaver.scrapers.run_ai_prompt', return_value=json.dumps(payload)) as model, self.assertRaises(validation.AnalysisValidationError):
            scrapers.process_job_with_ai('Python required','Python experience',denoise=False)
        self.assertEqual(model.call_count,2)
        self.assertIn('match_checks.1.posting_quote',model.call_args_list[1].args[0])

    def test_conflicts_require_standing_notes_and_explicit_hard_language(self):
        item=dict(preference='Location',notes_quote='I prefer remote work',posting_quote='On site',severity='hard')
        result=self.analyze({'preference_conflicts':[item]}, posting='On site', cv='I prefer remote work')
        self.assertEqual(result['preference_conflicts'],[])
        result=self.analyze({'preference_conflicts':[item]}, posting='On site',cv='CV\n\nRecent Experience & Standing Notes:\nI prefer remote work')
        self.assertEqual(result['preference_conflicts'][0]['severity'],'soft')
        hard=dict(item,notes_quote='I will only work remotely')
        result=self.analyze({'preference_conflicts':[hard]},posting='On site',cv='CV\n\nStanding Notes:\nI will only work remotely')
        self.assertEqual(result['match_rating'],'Blocked')
        self.assertEqual(result['preference_conflicts'][0]['severity'],'hard')
        # A later markdown CV section is not Standing Notes.
        result=self.analyze({'preference_conflicts':[hard]},posting='On site',cv='CV\n\n## Standing Notes\nI prefer remote work\n## Experience\nI will only work remotely')
        self.assertEqual(result['preference_conflicts'],[])

    def test_model_checklists_and_quote_excerpts_are_bounded(self):
        item = dict(checks('s')[0], posting_quote='Python required', cv_quote='Python experience')
        cases = ({'match_checks': [item] * 129},
                 {'match_checks': [dict(item, cv_quote='x' * 4001)]},
                 {'preference_conflicts': [conflict()] * 33},
                 {'requirements': ['Python required'], 'match_checks': []})
        for changes in cases:
            with self.subTest(changes=list(changes)), patch('jobweaver.scrapers.run_ai_prompt', return_value=json.dumps({
                    'german_level': 'none', 'summary': 'Role', 'match_checks': [], **changes})) as model, \
                    self.assertRaises(validation.AnalysisValidationError):
                scrapers.process_job_with_ai('Python required', 'Python experience', denoise=False)
            self.assertEqual(model.call_count, 2)
        result = self.analyze({'grounding_issues': [{'message': 'Private invented diagnostic'}]})
        self.assertEqual(result['grounding_issues'], [])
        self.assertEqual(result['grounding_status'], 'verified')

    def test_prompt_and_missing_checklist(self):
        prompt=scrapers._build_analysis_prompt('Python required','CV',False)
        self.assertNotIn('match_score',prompt)
        self.assertNotIn('0 to 100',prompt)
        with patch('jobweaver.scrapers.run_ai_prompt',return_value=json.dumps({'german_level':'none','summary':'Role','match_score':100})), self.assertRaises(validation.AnalysisValidationError):
            scrapers.process_job_with_ai('Python required','CV',denoise=False)


class RatingLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous=db.DB_PATH
        self.addCleanup(db.set_db_path,previous)
        db.set_db_path(os.path.join(self.temp.name,'ratings.db'))
        db.init_db()
        self.user=db.get_user_by_username('admin')
        self.other=db.create_user('rating-other',password_hash='x')
        self.config={'auto_generate':{'min_rating':'good','max_german_level':'B1'}}
        self.expected=fingerprint('CV','mock')
        self.record=dict(id='rated',title='Fictional role',company='Fictional',source='manual',date_scraped='2026-10-01',
                         processed=1,analysis_schema=2,analysis_state='complete',analysis_fingerprint=self.expected,
                         match_rating='Great',match_checks=checks('ssr'),preference_conflicts=[],german_level='none',german_strength='none')

    def save(self, **changes):
        record={**self.record,**changes};db.upsert_job(record,user_id=self.user['id']);return record

    def test_db_round_trip_updates_and_pending_leave_historical_and_unrated_alone(self):
        self.save()
        db.update_job_fields('rated',self.user['id'],match_checks=checks('ssm'),match_rating='Decent')
        stored=db.get_job_by_id('rated',self.user['id'])
        self.assertEqual((stored['match_rating'],stored['match_checks']),('Decent',checks('ssm')))
        self.save(id='legacy',analysis_schema=None,analysis_fingerprint='old',match_score=90,match_rating=None,match_checks=[])
        self.save(id='empty',match_rating='Unrated',match_checks=[])
        self.save(id='pending',processed=0,analysis_state='pending',match_rating=None)
        self.save(id='old-null',analysis_schema=None,analysis_state=None,match_rating=None,match_score=None)
        self.assertEqual({j['id'] for j in db.load_unprocessed_jobs(self.user['id'])},{'pending','old-null'})
        self.assertEqual(db.get_unprocessed_count(self.user['id']),2)
        self.assertTrue(analysis_current(db.get_job_by_id('empty',self.user['id']),self.expected))
        self.assertIsNone(db.get_job_by_id('rated',self.other['id']))

    def test_threshold_migration_and_historical_never_auto_generate(self):
        config={'auto_generate':{'min_match_score':99}}
        original=copy.deepcopy(config)
        self.assertEqual(normalize_rating_config(config)['auto_generate']['min_rating'],'good')
        self.assertEqual(config,original)
        self.assertEqual(validate_collection_config(config)['auto_generate'],{'min_rating':'good'})
        self.assertTrue(qualifies(self.record,config,self.expected))
        self.assertFalse(qualifies({**self.record,'match_score':100,'analysis_schema':None},config,self.expected))
        self.assertFalse(qualifies({**self.record,'analysis_state':'failed'},config,self.expected))
        self.assertFalse(qualifies(self.record,config,fingerprint('changed','mock')))
        # A threshold is inclusive, so Good qualifies for Good.
        good={**self.record,'match_checks':checks('srr')}
        self.assertTrue(qualifies(good,self.config,self.expected))
        self.assertFalse(qualifies(good,{'auto_generate':{'min_rating':'great'}},self.expected))

    def test_policy_updates_project_same_evidence_across_list_detail_stats_daily(self):
        self.save(german_level='C1',german_strength='required')
        self.save(id='legacy',analysis_schema=None,match_rating=None,match_score=100)
        with patch('jobweaver.server.load_cv_text',return_value='CV'), patch('jobweaver.server._effective_ai_model',return_value='mock'), \
             patch('jobweaver.server.user_outputs_dir',return_value=self.temp.name),patch('jobweaver.server.load_document_engine_config',return_value=('typst','base')):
            with patch('jobweaver.server.load_user_config_dict',return_value=self.config):
                jobs=server.get_jobs(user=self.user)
                rated=next(j for j in jobs if j['id']=='rated')
                self.assertEqual(rated['match_rating'],'Blocked')
                self.assertFalse(rated['qualifies'])
                self.assertEqual(server.get_job_detail('rated',user=self.user)['job']['match_rating'],'Blocked')
                stats=server.get_stats(user=self.user)
                self.assertEqual(stats['rated_jobs'],1)
                self.assertEqual(next(x['count'] for x in stats['match_rating_distribution'] if x['rating']=='Blocked'),1)
                self.assertEqual(server.get_daily_results('2026-10-01',user=self.user)['jobs'],[])
                self.assertFalse(next(j for j in jobs if j['id']=='legacy')['analysis_current'])
            allowed={'auto_generate':{'min_rating':'good'},'eligibility_policy':{'german_level':'C1'}}
            with patch('jobweaver.server.load_user_config_dict',return_value=allowed):
                self.assertEqual(server.get_job_detail('rated',user=self.user)['job']['match_rating'],'Great')
                daily=server.get_daily_results('2026-10-01',user=self.user)['jobs']
                self.assertEqual([j['id'] for j in daily],['rated'])
                self.assertTrue(daily[0]['analysis_current'])

    def test_single_job_rerate_owns_target_and_preserves_application(self):
        self.save(status='interview',application_date='2026-09-30',raw_description='Python required',match_score=90,analysis_schema=None)
        self.save(id='unrelated',processed=0,analysis_state='pending')
        self.save(id='other-user')
        with patch('jobweaver.server._require_cv'),patch('jobweaver.server._admit_background') as admit:
            with self.assertRaises(HTTPException) as error:
                server.api_reprocess_start(user=self.other,job_id='rated')
            self.assertEqual(error.exception.status_code,404)
            admit.assert_not_called()
            server.api_reprocess_start(user=self.user,job_id='rated')
            self.assertEqual(admit.call_args.args[2],{'all_scored':False,'job_id':'rated'})
        db.async_task_create('single-rerate','reprocess',total=1,user_id=self.user['id'])
        def analyze(job,user,cv,model):
            db.update_job_fields(job['id'],user_id=user['id'],analysis_schema=2,analysis_state='complete',processed=1,
                                 analysis_fingerprint=self.expected,match_rating='Great',match_checks=checks('sss'),match_score=None)
            return True,None
        with patch('jobweaver.server.load_cv_text',return_value='CV'),patch('jobweaver.server._effective_ai_model',return_value='mock'),patch('jobweaver.server._scrapers.analyse_stored_job',side_effect=analyze) as model:
            server._run_reprocess_bg('single-rerate',self.user,job_id='rated')
        self.assertEqual(model.call_count,1)
        self.assertEqual(model.call_args.args[0]['id'],'rated')
        job=db.get_job_by_id('rated',self.user['id'])
        self.assertEqual((job['status'],job['application_date']),('interview','2026-09-30'))
        self.assertEqual(db.get_job_by_id('unrelated',self.user['id'])['analysis_state'],'pending')

    def test_daily_scheduled_qualification_uses_current_rating_and_never_legacy_score(self):
        from jobweaver import daily_scraper
        import pandas as pd
        records=[self.record,{**self.record,'id':'legacy','analysis_schema':None,'match_score':100},
                 {**self.record,'id':'stale','analysis_fingerprint':'old'}]
        with patch('jobweaver.daily_scraper.load_config',return_value=self.config),patch('jobweaver.daily_scraper.load_effective_cv',return_value='CV'), \
             patch('jobweaver.daily_scraper.resolve_scrape_model',return_value='mock'),patch('jobweaver.daily_scraper.retry_failed_analyses',return_value=(0,0)), \
             patch('jobweaver.daily_scraper.db.load_jobs_by_date',return_value=pd.DataFrame(records)),patch('jobweaver.daily_scraper.scrape_new_jobs') as scrape, \
             patch('jobweaver.daily_scraper.logger.info') as info:
            daily_scraper._run_daily_for_user(self.user)
        scrape.assert_not_called()
        self.assertIn(unittest.mock.call('Daily scrape complete: %s qualifying jobs.',1),info.call_args_list)

    def test_manual_response_projects_current_eligibility_policy(self):
        payload={'german_level':'C1','german_strength':'required','german_evidence':'German C1 required',
                 'summary':'Role','match_checks':[dict(requirement='Python',importance='must',
                 posting_quote='Python required',coverage='shown',cv_quote='CV')]}
        with patch('jobweaver.scrapers.run_ai_prompt',return_value=json.dumps(payload)),patch('jobweaver.server.load_cv_text',return_value='CV'), \
             patch('jobweaver.server._effective_ai_model',return_value='mock'),patch('jobweaver.server.load_user_config_dict',return_value=self.config):
            response=server.add_job_manual(server.ManualJobRequest(title='Fictional',company='Example',
                description='Requirements: Python required. German C1 required'),user=self.user)
        self.assertEqual(response['job']['match_rating'],'Blocked')
        self.assertTrue(response['job']['analysis_current'])

    def test_real_analysis_save_path_stores_grounded_checklist(self):
        self.save(processed=0,analysis_state='pending',raw_description='Python required')
        payload={'german_level':'none','german_strength':'none','summary':'Role', 'match_checks':[
            dict(requirement='Python',importance='must',posting_quote='Python required',coverage='shown',cv_quote='CV')]}
        with patch('jobweaver.scrapers.run_ai_prompt',return_value=json.dumps(payload)):
            ok,error=scrapers.analyse_stored_job(db.get_job_by_id('rated',self.user['id']),self.user,'CV','mock')
        self.assertTrue(ok,error)
        stored=db.get_job_by_id('rated',self.user['id'])
        self.assertEqual(stored['match_checks'],payload['match_checks'])
        self.assertEqual(stored['match_rating'],'Great')
        self.assertEqual(stored['analysis_schema'],2)
        self.assertEqual(stored['grounding_status'],'verified')
        self.assertTrue(qualifies(stored,self.config,self.expected))


class DemoRatingEvidenceTest(unittest.TestCase):
    def test_all_demo_checks_and_conflicts_ground_against_fictional_profile(self):
        from jobweaver import career_record
        root=Path(__file__).resolve().parents[1]
        record,_=career_record.load(root/'examples/career_record.example.yaml')
        cv=career_record.scoring_text(record)+'\n\nRecent Experience & Standing Notes:\n'+(root/'examples/demo/standing-notes.md').read_text()
        labels=set()
        for job in json.loads((root/'examples/demo/jobs.json').read_text()):
            checked,conflicts,issues=validation.ground_match_checks(job['match_checks'],job['preference_conflicts'],job['description'],cv)
            self.assertEqual(issues,[],job['id'])
            self.assertEqual(checked,job['match_checks'])
            job.update(processed=1,analysis_state='complete')
            apply_rating(job,{'auto_generate':{'max_german_level':'B1'}})
            labels.add(job['match_rating'])
        self.assertEqual(labels,set(RATINGS)|{'Blocked'})
