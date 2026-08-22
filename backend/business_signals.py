"""Versioned, evidence-backed commercial signal engine."""
from __future__ import annotations
import hashlib,json,os,uuid
from datetime import date,datetime,timedelta,timezone

RULE_VERSION=os.getenv('SIGNAL_RULE_VERSION','1.0')
DEFINITIONS={
 'NEW_COMPANY':('New company','Company incorporated within the configured freshness window.','HIGH','creation_date'),
 'RECENT_INCORPORATION':('Recent incorporation','Company incorporated within the strongest recency window.','HIGH','creation_date'),
 'NO_WEBSITE':('No website','Completed website discovery found no qualified official website.','HIGH','digital_checks.Website=NOT_FOUND'),
 'WEAK_WEBSITE':('Weak website','Measured digital score is below the configured threshold.','MEDIUM','digital_score'),
 'WEAK_SEO':('Weak SEO','Completed SEO audit score is below the configured threshold.','HIGH','seo_audits.status=SUCCESS'),
 'NO_GOOGLE_BUSINESS':('No Google Business','Completed Google Places check found no qualified profile.','MEDIUM','digital_checks.Google Business=NOT_FOUND'),
 'DECISION_MAKER_FOUND':('Decision maker identified','Official director or high-confidence professional match is available.','POSITIVE','people evidence'),
 'HIGH_VALUE_NICHE':('High-value niche','Commercial niche attractiveness meets the configured threshold.','POSITIVE','niche_attractiveness')}

def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def parse_json(value):
    if isinstance(value,(dict,list)):return value
    try:return json.loads(value or '{}')
    except Exception:return {}

class BusinessSignalEngine:
    def __init__(self,db_connect):
        self.db_connect=db_connect;self.new_days=int(os.getenv('SIGNAL_NEW_COMPANY_DAYS','90'));self.recent_days=int(os.getenv('SIGNAL_RECENT_INCORPORATION_DAYS','30'));self.weak_seo=int(os.getenv('SIGNAL_WEAK_SEO_THRESHOLD','50'));self.weak_website=int(os.getenv('SIGNAL_WEAK_WEBSITE_THRESHOLD','40'));self.weak_website_factors=int(os.getenv('SIGNAL_WEAK_WEBSITE_MIN_FACTORS','2'));self.high_niche=int(os.getenv('SIGNAL_HIGH_VALUE_NICHE_THRESHOLD','80'));self.rule_version=os.getenv('SIGNAL_RULE_VERSION',RULE_VERSION)
    def status(self):return {'status':'READY','rule_version':self.rule_version,'definitions':len(DEFINITIONS),'rules':{'new_company_days':self.new_days,'recent_incorporation_days':self.recent_days,'weak_seo_threshold':self.weak_seo,'weak_website_threshold':self.weak_website,'weak_website_min_factors':self.weak_website_factors,'high_value_niche_threshold':self.high_niche},'guardrail':'NOT_FOUND requires a completed source check; NOT_CHECKED/UNKNOWN/NOT_CONNECTED/ERROR/BLOCKED never produce a negative signal.'}
    def sync_definitions(self):
        stamp=now()
        with self.db_connect() as db:
            for typ,(label,description,severity,evidence) in DEFINITIONS.items():db.execute("INSERT INTO business_signal_definitions(signal_type,label,description,severity,required_evidence,is_active,rule_version,created_at,updated_at) VALUES(?,?,?,?,?,TRUE,?,?,?) ON CONFLICT(signal_type) DO UPDATE SET label=excluded.label,description=excluded.description,severity=excluded.severity,required_evidence=excluded.required_evidence,is_active=TRUE,rule_version=excluded.rule_version,updated_at=excluded.updated_at",(typ,label,description,severity,evidence,self.rule_version,stamp,stamp))
    def detect(self,org,company_id):return self.refresh(org,company_id)['signals']
    def refresh(self,org,company_id=None):
        self.sync_definitions();run='signal_run_'+uuid.uuid4().hex;started=now()
        with self.db_connect() as db:
            db.execute("INSERT INTO business_signal_runs(id,organization_id,company_id,status,rule_version,started_at,metadata) VALUES(?,?,?,'RUNNING',?,?,?)",(run,org,company_id,self.rule_version,started,json.dumps({'scope':'COMPANY' if company_id else 'ORGANIZATION'})))
            if company_id:companies=[dict(x) for x in db.execute('SELECT * FROM companies WHERE organization_id=? AND id=?',(org,company_id)).fetchall()]
            else:companies=[dict(x) for x in db.execute('SELECT * FROM companies WHERE organization_id=?',(org,)).fetchall()]
        all_signals=[];activated=deactivated=0
        try:
            for company in companies:
                proposed=self._evaluate(org,company);active_types={x['signal_type'] for x in proposed};seen=now()
                with self.db_connect() as db:
                    old=[dict(x) for x in db.execute("SELECT signal_type,status FROM business_signals WHERE organization_id=? AND company_id=?",(org,company['id'])).fetchall()]
                    old_active={x['signal_type'] for x in old if x['status']=='ACTIVE'};deactivated+=len(old_active-active_types);activated+=len(active_types-old_active)
                    db.execute("UPDATE business_signals SET status='INACTIVE' WHERE organization_id=? AND company_id=?",(org,company['id']))
                    for signal in proposed:
                        sid='signal_'+hashlib.sha256((org+'|'+company['id']+'|'+signal['signal_type']).encode()).hexdigest()[:24]
                        db.execute("""INSERT INTO business_signals(id,organization_id,company_id,signal_type,signal_value,confidence,source,detected_at,status,first_detected_at,last_seen_at,evidence,severity,rule_version,explanation,expires_at,data_quality)
                        VALUES(?,?,?,?,?,?,?,?, 'ACTIVE',?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,company_id,signal_type) DO UPDATE SET signal_value=excluded.signal_value,confidence=excluded.confidence,source=excluded.source,status='ACTIVE',last_seen_at=excluded.last_seen_at,evidence=excluded.evidence,severity=excluded.severity,rule_version=excluded.rule_version,explanation=excluded.explanation,expires_at=excluded.expires_at,data_quality=excluded.data_quality""",
                        (sid,org,company['id'],signal['signal_type'],json.dumps(signal['value']),signal['confidence'],signal['source'],seen,seen,seen,json.dumps(signal['evidence']),signal['severity'],self.rule_version,signal['explanation'],signal.get('expires_at'),signal['data_quality']))
                all_signals.extend([{**x,'company_id':company['id'],'company_name':company['company_name']} for x in proposed])
            completed=now()
            with self.db_connect() as db:db.execute("UPDATE business_signal_runs SET status='SUCCESS',completed_at=?,companies_processed=?,active_signals=?,activated=?,deactivated=? WHERE id=?",(completed,len(companies),len(all_signals),activated,deactivated,run))
            return {'status':'SUCCESS','run_id':run,'companies_processed':len(companies),'active_signals':len(all_signals),'activated':activated,'deactivated':deactivated,'signals':all_signals}
        except Exception as exc:
            with self.db_connect() as db:db.execute("UPDATE business_signal_runs SET status='FAILED',completed_at=?,error_code='SIGNAL_ENGINE_FAILED',error_message=? WHERE id=?",(now(),str(exc)[:2000],run))
            return {'status':'FAILED','run_id':run,'message':str(exc),'signals':[]}
    @staticmethod
    def _fingerprint(company_id, signal_type, rule_version, value, evidence):
        """Deterministic SHA-256 over the signal identity + payload. Same inputs ->
        same fingerprint (idempotence / change detection). Proves content only."""
        canonical = json.dumps({'company': company_id, 'signal_type': signal_type,
                                'rule_version': rule_version, 'value': value,
                                'evidence': evidence}, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _evaluate(self, org, c):
        with self.db_connect() as db:
            checks = {x['channel']: dict(x) for x in db.execute('SELECT * FROM digital_checks WHERE organization_id=? AND company_id=?', (org, c['id'])).fetchall()}
            seo = db.execute('SELECT * FROM seo_audits WHERE organization_id=? AND company_id=?', (org, c['id'])).fetchone()
            seo = dict(seo) if seo else None
            drun = db.execute('SELECT status,selected_candidate_id,provider,error_code,candidates_found,started_at FROM website_discovery_runs WHERE organization_id=? AND company_id=? ORDER BY started_at DESC LIMIT 1', (org, c['id'])).fetchone()
            drun = dict(drun) if drun else None
            official_people = db.execute("SELECT count(*) count FROM people WHERE organization_id=? AND company_id=? AND privacy_status='ACTIVE' AND source_type='OFFICIAL' AND confidence>=.8", (org, c['id'])).fetchone()['count']
            profiles = db.execute("SELECT count(*) count FROM professional_profiles_public WHERE organization_id=? AND company_id=? AND match_confidence>=.82", (org, c['id'])).fetchone()['count']
            nace_active = db.execute("SELECT count(*) count FROM nace_versions_official WHERE version_code='2.1' AND status='ACTIVE'").fetchone()['count']
        base_quality = 'DEMO' if c.get('is_demo') else ('VERIFIED' if c.get('source_status') in ('VERIFIED', 'OFFICIAL') else 'OBSERVED')
        out = []

        def add(typ, value, confidence, source, evidence, explanation, expires=None, q=None):
            evidence = dict(evidence)
            evidence['fingerprint'] = self._fingerprint(c['id'], typ, self.rule_version, value, evidence)
            out.append({'signal_type': typ, 'value': value, 'confidence': confidence, 'source': source,
                        'evidence': evidence, 'explanation': explanation, 'severity': DEFINITIONS[typ][2],
                        'expires_at': expires, 'data_quality': q or base_quality})

        try:
            created = datetime.strptime(str(c.get('creation_date'))[:10], '%Y-%m-%d').date()
            age = (date.today() - created).days
            if 0 <= age <= self.new_days:
                add('NEW_COMPANY', {'age_days': age, 'creation_date': created.isoformat()}, 1.0, 'COMPANY_CREATION_DATE',
                    {'creation_date': created.isoformat()}, f'Company was incorporated {age} days ago.',
                    (created + timedelta(days=self.new_days + 1)).isoformat())
            if 0 <= age <= self.recent_days:
                add('RECENT_INCORPORATION', {'age_days': age, 'creation_date': created.isoformat()}, 1.0, 'COMPANY_CREATION_DATE',
                    {'creation_date': created.isoformat()}, f'Incorporation is within the {self.recent_days}-day high-freshness window.',
                    (created + timedelta(days=self.recent_days + 1)).isoformat())
        except Exception:
            pass

        # NO_WEBSITE: ONLY when a completed discovery (search executed) found no
        # evidence-backed candidate. NOT_CONFIGURED/ERROR/BLOCKED/unchecked/unknown
        # and a verify-404 never produce NO_WEBSITE. NOT_CONFIGURED != NOT_FOUND.
        if drun and drun.get('status') == 'SUCCESS' and not drun.get('selected_candidate_id') and not drun.get('error_code'):
            add('NO_WEBSITE', {'discovery_status': 'SUCCESS_NO_CANDIDATE', 'candidates_found': drun.get('candidates_found')},
                1.0, 'WEBSITE_DISCOVERY',
                {'provider': drun.get('provider'), 'run_started_at': drun.get('started_at'), 'candidates_found': drun.get('candidates_found')},
                'A completed website discovery (search executed) found no evidence-backed official website.',
                q='VERIFIED')

        # WEAK_WEBSITE: factor-based on the real Website digital_check metrics.
        # A NOT_CHECKED metric contributes nothing (never counts as weak).
        website = checks.get('Website')
        if website and website.get('status') == 'CONNECTED':
            det = parse_json(website.get('details'))
            factors = []
            if website.get('https_status') and website['https_status'] != 'VALID':
                factors.append('HTTPS')
            if det:
                if det.get('title') is None:
                    factors.append('TITLE')
                if det.get('h1') is None:
                    factors.append('H1')
                if det.get('has_viewport') is False:
                    factors.append('VIEWPORT')
                if det.get('canonical') is None:
                    factors.append('CANONICAL')
            if len(factors) >= self.weak_website_factors:
                add('WEAK_WEBSITE', {'factors': factors, 'count': len(factors)}, 0.8, 'DIGITAL_FOOTPRINT',
                    {'factors': factors, 'check_id': website.get('id'), 'final_url': website.get('final_url')},
                    f'Website weaknesses observed: {", ".join(factors)}.', q='OBSERVED')

        # WEAK_SEO: from a completed SEO audit; explanation lists the specific findings.
        if seo and seo.get('status') == 'SUCCESS' and seo.get('seo_score') is not None and seo['seo_score'] < self.weak_seo:
            findings = parse_json(seo.get('findings'))
            missing = [f['check'] for f in findings if isinstance(f, dict) and f.get('check')]
            add('WEAK_SEO', {'seo_score': seo['seo_score'], 'findings': missing}, 1.0, 'SEO_AUDIT',
                {'audit_id': seo.get('id'), 'checked_at': seo.get('checked_at'), 'threshold': self.weak_seo, 'findings': missing},
                f"SEO score {seo['seo_score']}/100 is below {self.weak_seo}: {', '.join(missing) or 'multiple issues'}.",
                q='VERIFIED')

        # NO_GOOGLE_BUSINESS: ONLY from a completed Google Places check (NOT_FOUND).
        # NOT_CONNECTED/NOT_CHECKED/unknown never produces this signal.
        google = checks.get('Google Business')
        if google and google.get('status') == 'NOT_FOUND' and google.get('source_provider') == 'google_places' and not google.get('error_code'):
            add('NO_GOOGLE_BUSINESS', {'check_status': 'NOT_FOUND'}, google.get('confidence') or 1.0, 'GOOGLE_PLACES',
                {'check_id': google.get('id'), 'checked_at': google.get('checked_at')},
                'A completed Google Business (Places) check found no qualified profile.',
                q='VERIFIED')

        # DECISION_MAKER_FOUND: only official published directors or high-confidence
        # public professional profiles. No guessing, no generated names.
        if official_people or profiles:
            add('DECISION_MAKER_FOUND', {'official_people': official_people, 'high_confidence_profiles': profiles},
                0.95 if official_people else 0.85, 'PEOPLE_ENGINE',
                {'official_people': official_people, 'profiles': profiles},
                'At least one official director or high-confidence professional profile is available.',
                q='VERIFIED')
        elif c.get('is_demo') and c.get('decision_maker_status') == 'FOUND':
            add('DECISION_MAKER_FOUND', {'demo': True}, 0.8, 'DEMO_PEOPLE', {'demo': True},
                'Synthetic demonstration decision-maker signal.', q='DEMO')

        # HIGH_VALUE_NICHE: from the existing NACELUX taxonomy attractiveness (never
        # invented; NULL/unknown -> no signal). Strengthens when NACE is ACTIVE.
        attractiveness = c.get('niche_attractiveness')
        if attractiveness is not None and attractiveness >= self.high_niche and not c.get('is_demo'):
            add('HIGH_VALUE_NICHE', {'attractiveness': attractiveness, 'nace_active': bool(nace_active)},
                0.75 if nace_active else 0.6, 'NACELUX_TAXONOMY',
                {'niche': c.get('niche'), 'attractiveness': attractiveness, 'threshold': self.high_niche, 'nace_active': bool(nace_active)},
                f'Niche attractiveness {attractiveness}/100 meets the {self.high_niche} threshold.' +
                (' Official NACE is ACTIVE.' if nace_active else ' Classification uses the NACELUX taxonomy (official NACE pending).'),
                q='INFERRED')
        return out
