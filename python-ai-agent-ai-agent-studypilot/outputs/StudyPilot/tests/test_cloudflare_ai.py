"""Cloudflare integration contracts: fake HTTP only, no real API quota."""
import io
import json
import os
import socket
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from studypilot.ai import (AIError, BACKUP, CLOUDFLARE, PRIMARY, FreeChatTransport,
                          ai_configured, configured_providers, provider_url)
from studypilot.agent import run_agent
from studypilot.proposals import execute_proposal, list_proposals
import test_free_ai as fixtures
from test_free_ai import FakeOpener, completion, function_call
from fastapi.testclient import TestClient
from studypilot.web import create_app

ACCOUNT = 'a' * 32
TOKEN = 'test-only-cloudflare-token'


def cf_error(code, status=429):
    return HTTPError('https://api.cloudflare.com/', status, 'private upstream text', {},
        io.BytesIO(json.dumps({'success': False, 'errors': [
            {'code': code, 'message': 'private learning data and token'}]}).encode()))


class CloudflareTests(fixtures.Base):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {'CLOUDFLARE_ACCOUNT_ID': ACCOUNT,
            'CLOUDFLARE_API_TOKEN': TOKEN, 'STUDYPILOT_AI_ENABLED': '1'})
        env.start()
        self.addCleanup(env.stop)

    def transport(self, *answers, **keys):
        opener = FakeOpener(*answers)
        return opener, FreeChatTransport(keys=keys, opener=opener)

    def test_cloudflare_only_uses_fixed_https_model_and_secret_header(self):
        opener, transport = self.transport(completion('Connected'))
        result = run_agent(self.auth, self.token, 'Connection test', transport=transport)
        self.assertEqual(result.text, 'Connected')
        req = opener.requests[0]
        self.assertEqual(req['url'], f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/v1/chat/completions')
        self.assertEqual(req['body']['model'], '@cf/zai-org/glm-4.7-flash')
        self.assertEqual(req['market']['Authorization'], 'Bearer '+TOKEN)
        self.assertFalse(req['body']['stream'])
        self.assertNotIn('thinking', req['body'])
        self.assertNotIn(TOKEN, json.dumps(req['body']))

    def test_zhipu_transient_failure_falls_back_to_cloudflare(self):
        for failure in (cf_error('1302'), socket.timeout(), cf_error('1305', 503)):
            with self.subTest(failure=type(failure).__name__):
                opener, transport = self.transport(failure, completion('Recovered'), zhipu='test-zhipu')
                self.assertEqual(run_agent(self.auth, self.token, 'Test', transport=transport).text, 'Recovered')
                self.assertEqual([r['body']['model'] for r in opener.requests], [PRIMARY.model, CLOUDFLARE.model])

    def test_all_three_configured_never_reaches_third_even_across_tool_rounds(self):
        opener, transport = self.transport(cf_error('1302'),
            completion(tool_calls=[function_call('get_study_profile', {})]), cf_error('3040'),
            completion('Must never call SiliconFlow'), zhipu='test-zhipu', siliconflow='test-sf')
        with self.assertRaises(AIError):
            run_agent(self.auth, self.token, 'Read profile', transport=transport)
        self.assertEqual([r['body']['model'] for r in opener.requests], [PRIMARY.model, CLOUDFLARE.model, CLOUDFLARE.model])
        self.assertEqual(configured_providers({'zhipu':'test', 'siliconflow':'test'}), (PRIMARY,CLOUDFLARE))

    def test_cloudflare_falls_back_to_existing_siliconflow(self):
        opener, transport = self.transport(socket.timeout(), completion('Recovered'), siliconflow='test-sf')
        self.assertEqual(run_agent(self.auth, self.token, 'Test', transport=transport).text, 'Recovered')
        self.assertEqual([r['body']['model'] for r in opener.requests], [CLOUDFLARE.model, BACKUP.model])

    def test_partial_or_invalid_config_is_skipped_without_request(self):
        for account in ('', 'invalid', ACCOUNT+'/../../evil', 'https://evil.example', 'b'*33):
            with self.subTest(account=account), patch.dict(os.environ, {'CLOUDFLARE_ACCOUNT_ID':account}):
                self.assertFalse(ai_configured())
                self.assertEqual(configured_providers(), ())
                opener, transport = self.transport(completion('Unused'))
                with self.assertRaises(AIError):
                    transport.create({}, timeout=20)
                self.assertEqual(opener.requests, [])
                with self.assertRaises(AIError):
                    provider_url(CLOUDFLARE)
        with patch.dict(os.environ, {'CLOUDFLARE_API_TOKEN':''}):
            self.assertFalse(ai_configured())

    def test_free_quota_paid_access_busy_errors_are_sanitized(self):
        for code, status, expected in [('3036',429,'今日免费额度已用完'),
                ('5035',403,'权限或套餐'), ('3040',429,'模型繁忙'), ('3040',401,'身份验证')]:
            with self.subTest(code=code, status=status):
                opener, transport = self.transport(cf_error(code, status), completion('Unused'))
                with self.assertLogs('studypilot.ai', level='WARNING') as logs, self.assertRaises(AIError) as caught:
                    transport.create({}, timeout=20)
                combined = str(caught.exception)+'\n'.join(logs.output)
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn(TOKEN, combined)
                self.assertNotIn('private', combined)
                self.assertEqual(len(opener.requests),1)

    def test_invalid_response_is_rejected_without_backup_or_writes(self):
        for response in ({'choices':[]}, completion(tool_calls=[{'function':{}}]),
                {'success':False,'errors':[{'code':5035}]}):
            with self.subTest(response=response):
                opener, transport = self.transport(response, completion('Unused'), siliconflow='test-sf')
                with self.assertRaises(AIError):
                    run_agent(self.auth, self.token, 'Test', transport=transport)
                self.assertEqual(len(opener.requests),1)
                self.assertEqual(self.db.get_tasks(),[])

    def test_cloudflare_proposes_change_without_confirmation_and_executes_once(self):
        opener, transport = self.transport(completion(tool_calls=[
            function_call('propose_task_create', {'task':self.task, 'reason':'User requested'})]),
            completion('Review this suggestion'))
        run_agent(self.auth, self.token, 'Create a task', transport=transport)
        self.assertEqual(self.db.get_tasks(),[])
        proposals = list_proposals(self.auth,self.token)
        self.assertEqual(len(proposals),1)
        from studypilot.database import ConfirmationRequired
        with self.assertRaises(ConfirmationRequired):
            execute_proposal(self.auth,self.token,proposals[0]['id'],confirmed=False)
        self.assertEqual(self.db.get_tasks(),[])
        execute_proposal(self.auth,self.token,proposals[0]['id'],confirmed=True)
        execute_proposal(self.auth,self.token,proposals[0]['id'],confirmed=True)
        self.assertEqual(len(self.db.get_tasks()),1)
        self.assertEqual([r['body']['model'] for r in opener.requests],[CLOUDFLARE.model]*2)


class CloudflareWebTests(fixtures.Base):
    def setUp(self):
        super().setUp()
        self.client = TestClient(create_app(lambda: self.auth))
        self.addCleanup(self.client.close)
        login = self.client.post('/api/login', json={'username':'learner','password':fixtures.PASSWORD},
                                 headers={'origin':'http://testserver'})
        self.assertEqual(login.status_code,200)
        self.headers = {'origin':'http://testserver','x-csrf-token':login.json()['csrf']}

    def test_cloudflare_status_never_exposes_token_and_setup_is_developer_only(self):
        with patch.dict(os.environ, {'CLOUDFLARE_ACCOUNT_ID':ACCOUNT,'CLOUDFLARE_API_TOKEN':TOKEN}):
            me = self.client.get('/api/me').json()
            self.assertEqual(me['ai_providers'],[CLOUDFLARE.label])
            self.assertIsNone(me['ai_setup'])
            self.assertEqual(me['default_model'],CLOUDFLARE.model)
            self.assertNotIn(TOKEN,json.dumps(me))
            self.auth.set_role('learner','developer',confirmed=True)
            me = self.client.get('/api/me').json()
            self.assertTrue(next(p for p in me['ai_setup'] if p['name']=='cloudflare')['configured'])
            self.assertNotIn(ACCOUNT,json.dumps(me))
            self.assertNotIn(TOKEN,json.dumps(me))

    def test_cloudflare_chat_requires_auth_consent_and_persistent_quota(self):
        with patch.dict(os.environ, {'CLOUDFLARE_ACCOUNT_ID':ACCOUNT,'CLOUDFLARE_API_TOKEN':TOKEN,
                                    'STUDYPILOT_AI_USER_LIMIT':'1'}):
            opener = FakeOpener(completion('Connected'))
            with patch('studypilot.ai.build_opener',return_value=opener):
                payload = {'prompt':'Test','consent':True}
                self.assertEqual(self.client.post('/api/agent',json={'prompt':'Test'},headers=self.headers).status_code,400)
                anonymous = TestClient(create_app(lambda: self.auth))
                self.addCleanup(anonymous.close)
                self.assertEqual(anonymous.post('/api/agent',json=payload,headers=self.headers).status_code,401)
                self.assertEqual(self.client.post('/api/agent',json=payload,headers=self.headers).status_code,200)
                self.assertEqual(self.client.post('/api/agent',json=payload,headers=self.headers).status_code,429)
                self.assertEqual(len(opener.requests),1)
