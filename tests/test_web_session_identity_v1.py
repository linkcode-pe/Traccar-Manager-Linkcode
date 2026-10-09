import unittest
from dataclasses import fields
from datetime import datetime, timezone

from api.identity_contract_v1 import VerifiedIdentity, DASHBOARD_OPERATION, DASHBOARD_ROLE
from api.read_only_dashboard_v1 import ActorContext, DashboardAPIError
from api.web_session_identity_v1 import (
    WebSessionEvidence, WebSessionState, actor_from_verified_web_session,
)

TRUSTED=frozenset({"panel-web"})
NOW=datetime(2026,10,1,18,0,0,tzinfo=timezone.utc)

class Roles:
    def __init__(self,roles):self.roles=roles;self.calls=0
    def roles_for(self,identity):self.calls+=1;return self.roles

def evidence(state=WebSessionState.AUTHENTICATED,identity=None,expires="2026-10-01T18:05:00Z",assertion="assertion-id-000001"):
    if identity is None and state is WebSessionState.AUTHENTICATED:identity=VerifiedIdentity("panel-web","opaque-subject-1")
    return WebSessionEvidence(state,identity,expires,assertion)

class WebSessionIdentityContractTests(unittest.TestCase):
    def test_valid_session_creates_minimum_dashboard_actor(self):
        roles=Roles(frozenset({DASHBOARD_ROLE,"admin"}))
        actor=actor_from_verified_web_session(evidence(),roles,trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertEqual(actor,ActorContext("opaque-subject-1",frozenset({DASHBOARD_ROLE})))
        self.assertEqual(roles.calls,1)

    def test_identity_absent_is_unauthorized(self):
        with self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(None,Roles(frozenset({DASHBOARD_ROLE})),trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertEqual(cm.exception.code,"API_UNAUTHORIZED")

    def test_session_absent_is_unauthorized(self):
        with self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(evidence(WebSessionState.ABSENT),Roles(frozenset({DASHBOARD_ROLE})),trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertEqual(cm.exception.code,"API_UNAUTHORIZED")

    def test_invalid_session_is_unauthorized(self):
        with self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(evidence(WebSessionState.INVALID),Roles(frozenset({DASHBOARD_ROLE})),trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertEqual(cm.exception.code,"API_UNAUTHORIZED")

    def test_expired_state_or_expiry_timestamp_is_unauthorized(self):
        roles=Roles(frozenset({DASHBOARD_ROLE}))
        with self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(evidence(WebSessionState.EXPIRED),roles,trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertEqual(cm.exception.code,"API_UNAUTHORIZED");self.assertEqual(roles.calls,0)
        with self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(evidence(expires="2026-10-01T17:59:59Z"),roles,trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertEqual(cm.exception.code,"API_UNAUTHORIZED");self.assertEqual(roles.calls,0)

    def test_malformed_or_untrusted_identity_is_unauthorized(self):
        roles=Roles(frozenset({DASHBOARD_ROLE}))
        bad=evidence(identity=VerifiedIdentity("other-issuer","opaque-subject-1"))
        with self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(bad,roles,trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertEqual(cm.exception.code,"API_UNAUTHORIZED")

    def test_role_valid_is_resolved_server_side(self):
        roles=Roles(frozenset({DASHBOARD_ROLE}))
        actor=actor_from_verified_web_session(evidence(),roles,trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertIn(DASHBOARD_ROLE,actor.roles);self.assertEqual(roles.calls,1)

    def test_role_insufficient_is_forbidden(self):
        with self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(evidence(),Roles(frozenset({"dashboard.write"})),trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertEqual(cm.exception.code,"API_FORBIDDEN")

    def test_operation_not_allowlisted_is_forbidden(self):
        with self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(evidence(),Roles(frozenset({DASHBOARD_ROLE})),trusted_issuers=TRUSTED,operation="dashboard.admin",now_utc=NOW)
        self.assertEqual(cm.exception.code,"API_FORBIDDEN")

    def test_client_roles_user_id_cookies_and_tokens_are_not_contract_fields(self):
        identity_fields={field.name for field in fields(VerifiedIdentity)}
        evidence_fields={field.name for field in fields(WebSessionEvidence)}
        self.assertEqual(identity_fields,{"issuer","subject_id"})
        self.assertEqual(evidence_fields,{"state","identity","expires_at_utc","assertion_id"})
        self.assertFalse({"role","roles","permissions","user_id","cookie","token","password"}&(identity_fields|evidence_fields))

    def test_bad_expiry_or_assertion_id_fails_closed(self):
        roles=Roles(frozenset({DASHBOARD_ROLE}))
        for item in (evidence(expires="not-a-time"),evidence(assertion="short")):
            with self.subTest(item=item),self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(item,roles,trusted_issuers=TRUSTED,now_utc=NOW)
            self.assertEqual(cm.exception.code,"API_UNAUTHORIZED")

    def test_stable_errors_do_not_disclose_auth_details(self):
        with self.assertRaises(DashboardAPIError) as cm:actor_from_verified_web_session(evidence(WebSessionState.INVALID),Roles(frozenset()),trusted_issuers=TRUSTED,now_utc=NOW)
        self.assertEqual(cm.exception.code,"API_UNAUTHORIZED")
        self.assertNotIn("cookie",str(cm.exception).lower())

if __name__=="__main__":unittest.main()
