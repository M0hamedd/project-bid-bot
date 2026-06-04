const PROFILE_ORDER = [
  "road_civil_infrastructure",
  "parks_landscape",
  "professional_engineering_design"
];

const DEFAULT_PROFILE_ID = PROFILE_ORDER[0];

const SNAPSHOT_MONTHS_2026 = [
  { value: "2026-01-31", label: "January", days: 30 },
  { value: "2026-02-28", label: "February", days: 30 },
  { value: "2026-03-31", label: "March", days: 30 },
  { value: "2026-04-30", label: "April", days: 30 },
  { value: "2026-05-30", label: "May", days: 30 }
];

const DEFAULT_SNAPSHOT_MONTH = SNAPSHOT_MONTHS_2026[SNAPSHOT_MONTHS_2026.length - 1].value;

const LOADING_PROFILE = {
  profile_id: "",
  label: "Loading business types",
  name: "Loading supported business types",
  business_type: "Waiting for city listings",
  base_location: "Toronto",
  skills: [],
  ready_documents: [],
  certifications: [],
  owned_equipment: [],
  recent_municipal_work: [],
  bid_constraints: [],
  top_divisions: [],
  good_fit_examples: [],
  bad_fit_examples: []
};

const state = {
  health: null,
  supportedProfiles: [],
  scan: null,
  selectedOpportunityId: "",
  activeView: "owner",
  priorityMode: "best_win_chance",
  selectedProfileId: DEFAULT_PROFILE_ID,
  selectedSnapshotMonth: DEFAULT_SNAPSHOT_MONTH,
  scanRequestId: 0,
  autoScanDone: false,
  progressiveOpportunities: [],
  backgroundScans: {},
  backgroundScanRequests: {},
  documentAnalyses: {},
  documentAcquireBusy: false,
  documentUploadBusy: false,
  evidenceUploadBusy: "",
  evidenceAttachTarget: null,
  complianceResolveBusy: "",
  pricingApproveBusy: false,
  profileSaveBusy: false
};

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
  renderProfileSelector();
  renderProfile(currentProfile());
  syncMonthSelector();
  bindEvents();
  resetWorkspace("Loading business types from City of Toronto data. First decision pass will run automatically.");
  setBusy(false);
  checkHealth();
});

function bindEvents() {
  $("scanButton").addEventListener("click", () => runScan(false));
  $("monthSelector").addEventListener("change", (event) => {
    state.selectedSnapshotMonth = event.target.value;
    updateSnapshotLabel();
    runSimulation();
  });
  $("approveButton").addEventListener("click", approveDraft);
  $("ownerTab").addEventListener("click", () => setView("owner"));
  $("evidenceTab").addEventListener("click", () => setView("evidence"));
  $("profileOptions").addEventListener("change", (event) => {
    const input = event.target;
    if (input && input.matches('input[name="supportedProfile"]')) {
      switchProfile(input.value);
    }
  });
  $("addProfileRateButton").addEventListener("click", addRateToCurrentProfile);
  $("saveProfileButton").addEventListener("click", () => saveCurrentProfile(currentProfile()));
}

async function checkHealth() {
  try {
    const health = await apiGet("/api/health");
    state.health = health;
    state.supportedProfiles = supportedProfilesFromHealth(health);
    state.selectedProfileId = selectProfileId(state.selectedProfileId);
    renderProfileSelector();
    renderProfile(currentProfile());
    if (!state.scan) {
      resetWorkspace(`${profileLabel(currentProfile())} loaded. Run the bid agent to queue today's work.`);
    }
    $("healthStatus").textContent = "City listings ready";
    $("healthStatus").className = "status-pill ok";
    $("dataStatus").textContent = "Data engine: ready";
    $("dataStatus").title = health.engine_story || "Bid department engine is ready.";
    $("briefStatus").textContent = `Brief: ${compactRuntimeStatus(health.briefs)}`;
    $("briefStatus").title = runtimeStatusDetail(health.briefs);
    if (!state.supportedProfiles.length) {
      setBusy(false);
      showToast("No supported business types were returned.");
      return;
    }
    if (!state.scan && !state.autoScanDone) {
      state.autoScanDone = true;
      await runScan(false, {
        busyMessage: `Running bid agent for ${selectedSnapshotMonth().label}`,
        doneMessage: `${selectedSnapshotMonth().label} agent tasks ready`,
        toast: false
      });
      return;
    }
    setBusy(false);
  } catch (error) {
    $("healthStatus").textContent = "City listings unavailable";
    $("healthStatus").className = "status-pill error";
    $("dataStatus").textContent = "Data engine: unknown";
    $("briefStatus").textContent = "Bid brief: unknown";
    state.supportedProfiles = [];
    renderProfileSelector();
    renderProfile(currentProfile());
    setBusy(false);
    showToast(error.message);
  }
}

async function runScan(refresh = false, options = {}) {
  const profile = currentProfile();
  const month = selectedSnapshotMonth();
  if (!profile.profile_id) {
    showToast("Business types are still loading.");
    return;
  }
  const requestId = ++state.scanRequestId;
  state.progressiveOpportunities = [];
  setBusy(true, options.busyMessage || `Running bid agent for ${month.label}`);
  const payload = {
    profile_id: profile.profile_id,
    business_profile: profile,
    priority_mode: getPriorityMode(),
    as_of: month.value,
    refresh
  };
  try {
    const result = await apiPostStream("/api/scan-stream", payload, (event) => {
      if (requestId !== state.scanRequestId || profile.profile_id !== state.selectedProfileId) {
        return;
      }
      handleScanProgress(event, profile, month);
    });
    if (requestId !== state.scanRequestId || profile.profile_id !== state.selectedProfileId) {
      return;
    }
    ingestResult(result, options.doneMessage || `${month.label} agent tasks ready`, {
      toast: options.toast !== false
    });
    warmOtherProfileScans(result);
  } catch (error) {
    showToast(error.message);
  } finally {
    if (requestId === state.scanRequestId) {
      setBusy(false);
    }
  }
}

function switchProfile(profileId) {
  state.selectedProfileId = profileId;
  state.selectedOpportunityId = "";
  state.scan = null;
  state.progressiveOpportunities = [];
  const profile = currentProfile();
  const month = selectedSnapshotMonth();
  const cached = cachedScanFor(profile.profile_id, getPriorityMode(), month.value);
  renderProfile(profile);

  if (cached) {
    ingestResult(cached, `${profileLabel(profile)} agent tasks ready`, { toast: false });
    setBusy(false);
    warmOtherProfileScans(cached);
    return;
  }

  const key = backgroundScanKey(profile.profile_id, getPriorityMode(), month.value);
  const pending = state.backgroundScanRequests[key];
  if (pending) {
    resetWorkspace(`${profileLabel(profile)} is almost ready. Finishing the agent task queue.`);
    setBusy(true, `Opening ${profileLabel(profile)} queue`);
    pending
      .then((result) => {
        if (
          state.selectedProfileId === profile.profile_id
          && getPriorityMode() === result.priority_mode
          && selectedSnapshotMonth().value === result.as_of
        ) {
          ingestResult(result, `${profileLabel(profile)} agent tasks ready`, { toast: false });
          setBusy(false);
          warmOtherProfileScans(result);
        }
      })
      .catch((error) => {
        if (state.selectedProfileId === profile.profile_id) {
          showToast(error.message);
          setBusy(false);
        }
      });
    return;
  }

  resetWorkspace(`${profileLabel(profile)} selected. Re-running the bid agent for this lane.`);
  runScan(false, {
    busyMessage: `Running bid agent for ${profileLabel(profile)}`,
    doneMessage: `${profileLabel(profile)} agent tasks ready`,
    toast: false
  });
}

async function runSimulation(options = {}) {
  const profile = currentProfile();
  const month = selectedSnapshotMonth();
  if (!profile.profile_id) {
    showToast("Business types are still loading.");
    return;
  }
  const requestId = ++state.scanRequestId;
  setBusy(true, options.busyMessage || `Refreshing ${month.label} agent tasks`);
  try {
    const result = await apiPost("/api/simulate", {
      profile_id: profile.profile_id,
      business_profile: profile,
      priority_mode: getPriorityMode(),
      as_of: month.value,
      days: month.days
    });
    if (requestId !== state.scanRequestId || profile.profile_id !== state.selectedProfileId) {
      return;
    }
    ingestResult(result, options.doneMessage || `${month.label} agent tasks ready`, {
      toast: options.toast !== false
    });
  } catch (error) {
    showToast(error.message);
  } finally {
    if (requestId === state.scanRequestId) {
      setBusy(false);
    }
  }
}

async function approveDraft() {
  if (!state.selectedOpportunityId) {
    showToast("Select a city listing first.");
    return;
  }

  setBusy(true, `Preparing ${approvalArtifactNoun()}`);
  try {
    const profile = currentProfile();
    const documentAnalysis = selectedDocumentAnalysis();
    const result = await apiPost("/api/approve", {
      profile_id: profile.profile_id,
      business_profile: profile,
      priority_mode: getPriorityMode(),
      as_of: selectedSnapshotMonth().value,
      approved: true,
      opportunity_id: state.selectedOpportunityId,
      analysis_id: documentAnalysis ? documentAnalysis.analysis_id : ""
    });
    renderPacket(result.packet, result.approved, result.packet_export);
    $("packetStatus").textContent = result.approved ? "Prepared" : "Needs a closer look";
    showToast(`${approvalArtifactTitle()} prepared`);
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(false);
  }
}

function ingestResult(result, message, options = {}) {
  state.progressiveOpportunities = [];
  hydrateDocumentAnalyses(result);
  state.scan = result;
  cacheScanResult(result);
  const resultMonth = snapshotMonthForDate(result.as_of);
  if (resultMonth) {
    state.selectedSnapshotMonth = resultMonth.value;
    syncMonthSelector();
  }
  state.selectedProfileId = selectProfileId(
    (result.business_profile && result.business_profile.profile_id) || state.selectedProfileId
  );
  const top = result.top_opportunities || [];
  const watch = result.watchlist || [];
  const selected = top[0] || watch[0] || null;
  state.selectedOpportunityId = selected ? getOpportunityId(selected) : "";

  renderProfileSelector();
  renderProfile(result.business_profile || currentProfile());
  updateSnapshotLabel();
  renderOwner(result);
  renderEvidence(result);
  $("approveButton").disabled = !canApproveCurrent();
  if (options.toast !== false) {
    showToast(message);
  }
}

async function saveCurrentProfile(profile, options = {}) {
  const payloadProfile = profile && profile.profile_id ? profile : currentProfile();
  if (!payloadProfile.profile_id) {
    showToast("Business types are still loading.");
    return;
  }
  state.profileSaveBusy = true;
  renderProfile(payloadProfile);
  try {
    const result = await apiPost("/api/profile/save", {
      profile_id: payloadProfile.profile_id,
      business_profile: payloadProfile
    });
    applySavedProfile(result.business_profile, result.supported_profiles);
    showToast(options.message || "Company profile saved");
  } catch (error) {
    showToast(error.message);
  } finally {
    state.profileSaveBusy = false;
    renderProfile(currentProfile());
  }
}

async function addRateToCurrentProfile() {
  const profile = currentProfile();
  if (!profile.profile_id) {
    showToast("Business types are still loading.");
    return;
  }
  const label = window.prompt("Rate label, for example Asphalt paving");
  if (label === null) {
    return;
  }
  const keywords = window.prompt("Match words, comma-separated, for example asphalt, paving", label);
  if (keywords === null) {
    return;
  }
  const unit = window.prompt("Unit, for example m2, linear m, each, hour", "m2");
  if (unit === null) {
    return;
  }
  const rawCost = window.prompt("Unit direct cost in CAD", "");
  if (rawCost === null) {
    return;
  }
  const unitDirectCost = Number(String(rawCost).replace(/[$,]/g, "").trim());
  const cleanKeywords = splitCommaList(keywords);
  const cleanUnit = String(unit || "").trim();
  const cleanLabel = String(label || "").trim();
  if (!cleanLabel || !cleanKeywords.length || !cleanUnit || !Number.isFinite(unitDirectCost) || unitDirectCost <= 0) {
    showToast("Add a label, match words, unit, and positive unit cost.");
    return;
  }
  const existingRates = Array.isArray(profile.pricing_rate_card) ? profile.pricing_rate_card : [];
  const nextProfile = {
    ...profile,
    pricing_rate_card: [
      ...existingRates,
      {
        rate_id: uniqueProfileRateId(existingRates, cleanLabel, cleanUnit),
        label: cleanLabel,
        keywords: cleanKeywords,
        units: [cleanUnit],
        unit_direct_cost: unitDirectCost,
        confidence: "High"
      }
    ]
  };
  await saveCurrentProfile(nextProfile, { message: "Company rate saved" });
}

function applySavedProfile(profile, supportedProfiles) {
  if (!profile || !profile.profile_id) {
    return;
  }
  if (Array.isArray(supportedProfiles) && supportedProfiles.length) {
    state.supportedProfiles = supportedProfilesFromHealth({ supported_profiles: supportedProfiles });
  } else {
    const index = state.supportedProfiles.findIndex((item) => item.profile_id === profile.profile_id);
    if (index >= 0) {
      state.supportedProfiles[index] = { ...state.supportedProfiles[index], ...profile };
    } else {
      state.supportedProfiles.push(profile);
    }
  }
  state.selectedProfileId = profile.profile_id;
  state.backgroundScans = {};
  state.backgroundScanRequests = {};
  if (state.scan && state.scan.business_profile && state.scan.business_profile.profile_id === profile.profile_id) {
    state.scan.business_profile = profile;
  }
  renderProfileSelector();
  renderProfile(profile);
  if (state.scan) {
    renderOwner(state.scan);
    renderEvidence(state.scan);
  }
}

function warmOtherProfileScans(result) {
  const activeProfileId = result && result.business_profile && result.business_profile.profile_id;
  const monthValue = (result && result.as_of) || selectedSnapshotMonth().value;
  const priorityMode = (result && result.priority_mode) || getPriorityMode();
  state.supportedProfiles
    .filter((profile) => profile.profile_id && profile.profile_id !== activeProfileId)
    .forEach((profile) => {
      warmProfileScan(profile, priorityMode, monthValue).catch(() => {});
    });
}

function warmProfileScan(profile, priorityMode, monthValue) {
  const key = backgroundScanKey(profile.profile_id, priorityMode, monthValue);
  if (state.backgroundScans[key] || state.backgroundScanRequests[key]) {
    return state.backgroundScanRequests[key] || Promise.resolve(state.backgroundScans[key]);
  }

  const request = apiPostStream("/api/scan-stream", {
    profile_id: profile.profile_id,
    business_profile: profile,
    priority_mode: priorityMode,
    as_of: monthValue,
    refresh: false
  }, () => {})
    .then((result) => {
      cacheScanResult(result);
      delete state.backgroundScanRequests[key];
      if (state.selectedProfileId === profile.profile_id && !state.scan) {
        ingestResult(result, `${profileLabel(profile)} agent tasks ready`, { toast: false });
      }
      return result;
    })
    .catch((error) => {
      delete state.backgroundScanRequests[key];
      console.warn("Background agent run failed", profile.profile_id, error);
      throw error;
    });

  state.backgroundScanRequests[key] = request;
  return request;
}

function cacheScanResult(result) {
  const profileId = result && result.business_profile && result.business_profile.profile_id;
  const priorityMode = result && result.priority_mode;
  const monthValue = result && result.as_of;
  if (!profileId || !priorityMode || !monthValue) {
    return;
  }
  state.backgroundScans[backgroundScanKey(profileId, priorityMode, monthValue)] = result;
}

function cachedScanFor(profileId, priorityMode, monthValue) {
  return state.backgroundScans[backgroundScanKey(profileId, priorityMode, monthValue)] || null;
}

function backgroundScanKey(profileId, priorityMode, monthValue) {
  return [profileId, priorityMode, monthValue].join("|");
}

function handleScanProgress(event, profile, month) {
  if (!event || event.event === "done") {
    return;
  }
  if (event.event === "stage") {
    renderScanProgressMessage(event.message || `Checking ${month.label} contracts`);
    return;
  }
  if (event.event === "match" && event.opportunity) {
    upsertProgressOpportunity(event.opportunity, event.preliminary !== false);
    renderProgressiveOpportunities(profile, month, event.message || "Good match found.");
    return;
  }
  if (event.event === "matches" && Array.isArray(event.opportunities)) {
    event.opportunities.forEach((item) => upsertProgressOpportunity(item, event.preliminary !== false));
    renderProgressiveOpportunities(profile, month, event.message || "Promising matches found.");
  }
}

function renderScanProgressMessage(message) {
  $("lastRun").textContent = ownerText(message || "Checking Toronto contracts");
  if (!state.progressiveOpportunities.length) {
    $("decisionHeadline").textContent = "Checking city listings";
    $("topOpportunities").className = "docket-list empty-list";
    $("topOpportunities").innerHTML = `<p>${escapeHtml(ownerText(message || "Checking Toronto contracts for good matches."))}</p>`;
  }
}

function upsertProgressOpportunity(item, preliminary) {
  const id = getOpportunityId(item);
  if (!id) {
    return;
  }
  const decorated = { ...item, _preliminary_match: preliminary };
  const existingIndex = state.progressiveOpportunities.findIndex((candidate) => getOpportunityId(candidate) === id);
  if (existingIndex >= 0) {
    state.progressiveOpportunities[existingIndex] = decorated;
  } else {
    state.progressiveOpportunities.push(decorated);
  }
  state.progressiveOpportunities = state.progressiveOpportunities
    .filter((candidate) => decisionLabel(candidate.label) !== "Skip")
    .sort((a, b) => Number(b.rank_score || 0) - Number(a.rank_score || 0))
    .slice(0, 10);
}

function renderProgressiveOpportunities(profile, month, message) {
  const opportunities = state.progressiveOpportunities;
  if (!opportunities.length) {
    renderScanProgressMessage(message);
    return;
  }
  const stillSelected = opportunities.some((item) => getOpportunityId(item) === state.selectedOpportunityId);
  if (!stillSelected) {
    state.selectedOpportunityId = getOpportunityId(opportunities[0]);
  }
  const partial = {
    business_profile: profile,
    as_of: month.value,
    priority_mode: getPriorityMode(),
    top_opportunities: opportunities,
    watchlist: [],
    skipped: [],
    all_evaluated: opportunities,
    metrics: {}
  };
  state.scan = partial;
  renderOwner(partial);
  $("decisionHeadline").textContent = "Promising matches are appearing";
  $("lastRun").textContent = ownerText(message || "Showing good contracts as they are found.");
  $("approveButton").disabled = true;
}

function renderProfileSelector() {
  const container = $("profileOptions");
  if (!container) {
    return;
  }
  const profiles = state.supportedProfiles;
  if (!profiles.length) {
    container.innerHTML = "<p class=\"profile-loading\">Loading business types...</p>";
    return;
  }
  container.innerHTML = profiles.map((profile) => `
    <label>
      <input type="radio" name="supportedProfile" value="${escapeHtml(profile.profile_id)}" ${profile.profile_id === state.selectedProfileId ? "checked" : ""}>
      <span class="profile-lens-copy">
        <strong>${escapeHtml(compactProfileLabel(profile))}</strong>
      </span>
    </label>
  `).join("");
}

function renderProfile(profile) {
  const active = profile && profile.profile_id ? profileWithSupportedEvidence(profile) : currentProfile();
  $("profileName").textContent = compactProfileLabel(active);
  $("profileType").textContent = titleCase(active.business_type || "Not listed");
  $("profileBase").textContent = active.base_location || active.service_area || "Not listed";
  $("profileYears").textContent = active.years_in_business ? `${active.years_in_business} years` : "Not listed";
  $("profileTeam").textContent = active.team_size ? `${active.team_size} people` : "Not listed";
  $("profileCrew").textContent = active.crew_mix || "Not listed";
  $("profileCapacity").textContent = profileCapacityText(active);
  $("profileInsurance").textContent = active.insurance_coverage || "Not listed";
  $("profileBonding").textContent = profileBondingText(active);
  $("profilePursuits").textContent = profilePursuitsText(active);
  $("profileEstimating").textContent = active.estimating_capacity || "Not listed";
  renderTags($("profileSkills"), active.skills || []);
  renderTags($("profileDocs"), active.ready_documents || []);
  renderTags($("profileAssets"), [
    ...(active.owned_equipment || []),
    ...(active.certifications || [])
  ]);
  renderTags($("profileRecentWork"), active.recent_municipal_work || []);
  renderTags($("profileConstraints"), active.bid_constraints || []);
  renderTags($("profileRateCard"), profileRateCardLabels(active));
  if ($("addProfileRateButton")) {
    $("addProfileRateButton").disabled = state.profileSaveBusy || !active.profile_id;
  }
  if ($("saveProfileButton")) {
    $("saveProfileButton").disabled = state.profileSaveBusy || !active.profile_id;
    $("saveProfileButton").textContent = state.profileSaveBusy ? "Saving..." : "Save Profile";
  }
  renderProfileEvidence(active);
}

function resetWorkspace(message) {
  updateSnapshotLabel();
  $("decisionHeadline").textContent = "Ready to run the bid agent";
  $("lastRun").textContent = message || "Agent has not run yet";
  $("summaryRecommendation").textContent = "Waiting";
  $("summaryDeadline").textContent = "Not checked";
  $("summaryTask").textContent = "Ranking current listings";
  $("summaryFit").textContent = "No signal yet";
  $("topCount").textContent = "0";
  $("watchCount").textContent = "0";
  $("timelineCount").textContent = "0";
  $("topOpportunities").className = "docket-list empty-list";
  $("topOpportunities").innerHTML = "<p>The agent will list supporting contracts after it queues the first tasks.</p>";
  $("watchlist").className = "docket-list empty-list";
  $("watchlist").innerHTML = "<p>Listings to keep an eye on will appear here.</p>";
  $("selectedOpportunityDetail").className = "selected-detail empty-list";
  $("selectedOpportunityDetail").innerHTML = "<p>Select a city listing to see what it is, why it matched, and what to do next.</p>";
  $("gateStatus").textContent = "Waiting";
  $("decisionGateChecklist").className = "gate-checklist empty-list";
  $("decisionGateChecklist").innerHTML = "<p>Run the bid agent to see whether the selected task can become bid notes.</p>";
  $("timeline").hidden = true;
  $("timeline").className = "timeline empty-list";
  $("timeline").innerHTML = "<p>Pick a month to see deadline reminders and next steps.</p>";
  $("packetStatus").textContent = "Not ready";
  $("packetOutput").hidden = true;
  $("packetOutput").className = "packet-output empty-list";
  $("packetOutput").innerHTML = `<p>Select a listing and prepare ${approvalArtifactNoun()} when the ready check passes.</p>`;
  $("metricSolicitations").textContent = "0";
  $("metricAwards").textContent = "0";
  $("metricRejected").textContent = "0";
  $("metricRuntime").textContent = "0 ms";
  $("metricRecordsPerSecond").textContent = "0";
  $("metricModelCallsAvoided").textContent = "0";
  $("metricRuntimePath").textContent = "Pending";
  $("metricBacktestInsight").textContent = "0";
  $("engineLabel").textContent = "Python";
  $("skipCount").textContent = "0";
  $("evaluatedCount").textContent = "0";
  $("pipelineDetails").className = "scorecard-grid empty-list";
  $("pipelineDetails").innerHTML = "<p>Proof appears after the bid agent runs.</p>";
  $("skippedExamples").className = "scorecard-grid empty-list";
  $("skippedExamples").innerHTML = "<p>Pricing stats appear after the value model runs.</p>";
  $("scorecardStatus").textContent = "Waiting";
  $("scorecardDetails").className = "scorecard-grid empty-list";
  $("scorecardDetails").innerHTML = "<p>Run the bid agent to see validation proof.</p>";
  $("evaluatedStream").className = "table-list empty-list";
  $("evaluatedStream").innerHTML = "<p>Run the bid agent to inspect every listing it checked.</p>";
  $("approveButton").disabled = true;
}

function renderOwner(result) {
  updateSnapshotLabel();
  const top = result.top_opportunities || [];
  const watch = result.watchlist || [];
  const inboxItems = [...top, ...watch];
  const timeline = result.timeline || [];
  const metrics = result.metrics || {};
  const topDecision = top[0] || watch[0];
  const selected = findSelectedOpportunity() || topDecision;
  const summary = selected ? nextActionSummary(selected) : null;

  $("decisionHeadline").textContent = selected
    ? `${summary.recommendation}: ${summary.deadline}; ${shortText(summary.task, 78)}`
    : "No strong match found today";
  $("lastRun").textContent = result.as_of
    ? `As of ${result.as_of}`
    : "Latest check";
  $("summaryRecommendation").textContent = summary ? summary.recommendation : "No strong match";
  $("summaryDeadline").textContent = summary ? summary.deadline : "No active listing";
  $("summaryTask").textContent = summary ? summary.task : "See why we passed";
  $("summaryFit").textContent = summary ? summary.fit : "No strong match";

  const actionInbox = dailyInboxFromState(result);
  $("topCount").textContent = String((actionInbox.items || []).filter((item) => !["watch", "passed"].includes(item.status)).length);
  $("watchCount").textContent = "0";
  $("timelineCount").textContent = String(timeline.length);

  renderDailyInboxPanel(actionInbox);
  renderOpportunityList($("topOpportunities"), inboxItems, "No good matches found.");
  renderOpportunityList($("watchlist"), [], "No listings to keep watching yet.");
  renderSelectedOpportunityDetail(selected);
  renderDecisionGate(selected, result);
  renderTimeline(timeline);

  if (!metrics || Object.keys(metrics).length === 0) {
    $("packetStatus").textContent = "Not ready";
  }
}

function renderEvidence(result) {
  const metrics = result.metrics || {};
  const skipped = result.skipped || [];
  const evaluated = result.all_evaluated || [];
  const scorecard = result.insight_scorecard || result.scorecard || {};

  $("metricSolicitations").textContent = number(metrics.solicitations_loaded);
  $("metricAwards").textContent = number(metrics.awards_loaded);
  $("metricRejected").textContent = number(metrics.rejected_count);
  $("metricRuntime").textContent = `${number(metrics.runtime_ms)} ms`;
  $("metricRecordsPerSecond").textContent = number(metrics.records_per_second);
  $("metricModelCallsAvoided").textContent = number(metrics.model_calls_avoided);
  $("metricRuntimePath").textContent = runtimePathLabel(metrics);
  $("metricBacktestInsight").textContent = number(scorecard.realistic_historical_opportunities);
  $("engineLabel").textContent = metrics.engine || "python";
  $("skipCount").textContent = String(pricedOpportunities(result).length);
  $("evaluatedCount").textContent = String(evaluated.length);

  renderPipeline(metrics, result);
  renderPricingStats(result);
  renderScorecard(result);
  renderEvaluatedStream(evaluated);
}

function hydrateDocumentAnalyses(result) {
  const analyses = result && result.document_analyses;
  if (!analyses || typeof analyses !== "object") {
    return;
  }
  Object.entries(analyses).forEach(([opportunityId, analysis]) => {
    if (!opportunityId || !analysis || typeof analysis !== "object") {
      return;
    }
    state.documentAnalyses[opportunityId] = analysis;
  });
}

function renderDailyInboxPanel(inbox) {
  const panel = $("dailyInboxPanel");
  if (!panel) {
    return;
  }
  const items = Array.isArray(inbox && inbox.items) ? inbox.items : [];
  if (!items.length) {
    panel.className = "agent-action-queue empty-list";
    panel.innerHTML = "<p>Run the bid agent to queue the tasks worth doing.</p>";
    return;
  }

  const actionable = items.filter((item) => !["watch", "passed"].includes(item.status));
  const visibleTasks = (actionable.length ? actionable : items).slice(0, 4);
  panel.className = "agent-action-queue";
  panel.innerHTML = `
    <div class="agent-action-head">
      <span class="selected-detail-label">Queued By Agent</span>
      <strong>${escapeHtml(`${visibleTasks.length} task${visibleTasks.length === 1 ? "" : "s"} worth doing now`)}</strong>
      ${renderDailyRunSummary(inbox.run_summary)}
    </div>
    ${visibleTasks.map((item, index) => renderAgentQueueTask(item, index)).join("")}
  `;
  panel.querySelectorAll(".agent-queue-open").forEach((button) => {
    button.addEventListener("click", () => {
      const opportunityId = button.dataset.opportunityId || "";
      if (!opportunityId) {
        return;
      }
      state.selectedOpportunityId = opportunityId;
      $("approveButton").disabled = !canApproveCurrent();
      renderOwner(state.scan);
      renderEvidence(state.scan);
    });
  });
}

function renderAgentQueueTask(item, index) {
  const selected = item.opportunity_id === state.selectedOpportunityId ? " selected" : "";
  const statusLabel = item.label || item.status_label || dailyInboxStatusLabel(item.status);
  const stateLabel = item.task_state ? `${humanizeToken(item.task_state)}${item.change_reason ? ` / ${item.change_reason}` : ""}` : "";
  return `
    <article class="agent-queue-task agent-task-${escapeHtml(item.status)}${selected}">
      <div class="agent-queue-index">${escapeHtml(String(index + 1))}</div>
      <div>
        <span>${escapeHtml(statusLabel)}</span>
        <strong>${escapeHtml(cleanDisplayText(item.next_action || "Open listing"))}</strong>
        <p>${escapeHtml(`${item.opportunity_id}${item.deadline_label ? ` / ${item.deadline_label}` : ""}${stateLabel ? ` / ${stateLabel}` : ""}`)}</p>
      </div>
      <button class="agent-queue-open" type="button" data-opportunity-id="${escapeHtml(item.opportunity_id)}">Open</button>
    </article>
  `;
}

function renderDailyRunSummary(summary) {
  if (!summary || typeof summary !== "object") {
    return "";
  }
  const parts = [
    summary.new ? `${number(summary.new)} new` : "",
    summary.changed ? `${number(summary.changed)} changed` : "",
    summary.resolved ? `${number(summary.resolved)} resolved` : "",
    summary.deadline_alerts ? `${number(summary.deadline_alerts)} deadline alert${summary.deadline_alerts === 1 ? "" : "s"}` : "",
    summary.package_alerts ? `${number(summary.package_alerts)} package update${summary.package_alerts === 1 ? "" : "s"}` : "",
    summary.addenda_alerts ? `${number(summary.addenda_alerts)} addendum alert${summary.addenda_alerts === 1 ? "" : "s"}` : "",
    summary.change_events ? `${number(summary.change_events)} source change${summary.change_events === 1 ? "" : "s"}` : ""
  ].filter(Boolean);
  if (!parts.length) {
    parts.push("No task changes since the last run");
  }
  return `<em>${escapeHtml(parts.join(" / "))}</em>`;
}

function dailyInboxFromState(result) {
  if (result && result.daily_inbox && Array.isArray(result.daily_inbox.items)) {
    return {
      ...result.daily_inbox,
      items: result.daily_inbox.items.map((item) => ({
        ...item,
        label: item.label || item.status_label || dailyInboxStatusLabel(item.status),
        deadline_label: item.deadline_label || deadlineLabelFromDays(item.days_until_deadline)
      }))
    };
  }
  const items = scanOpportunityPool(result).map((item) => dailyInboxItem(item)).filter(Boolean);
  const sorted = items.sort(dailyInboxSort).slice(0, 12);
  const counts = sorted.reduce((acc, item) => {
    acc[item.status] = (acc[item.status] || 0) + 1;
    return acc;
  }, {});
  const top = sorted[0] || {};
  return {
    summary: {
      total: sorted.length,
      ready_for_packet: counts.ready_for_packet || 0,
      needs_action: (counts.resolve_gates || 0) + (counts.get_package || 0) + (counts.review_fit || 0),
      needs_package: counts.get_package || 0,
      top_action: top.next_action || "Run a scan to build the daily bid inbox.",
      top_opportunity_id: top.opportunity_id || ""
    },
    sections: dailyInboxSections(sorted),
    items: sorted
  };
}

function deadlineLabelFromDays(days) {
  if (days === undefined || days === null || days === "") {
    return "";
  }
  const value = Number(days);
  if (!Number.isFinite(value)) {
    return "";
  }
  if (value < 0) {
    return `${Math.abs(Math.round(value))} days late`;
  }
  return `${Math.round(value)} days left`;
}

function scanOpportunityPool(result) {
  const buckets = [
    ...((result && result.top_opportunities) || []),
    ...((result && result.watchlist) || []),
    ...((result && result.all_evaluated) || []),
    ...((result && result.skipped) || [])
  ];
  const seen = new Set();
  return buckets.filter((item) => {
    const id = getOpportunityId(item);
    if (!id || seen.has(id)) {
      return false;
    }
    seen.add(id);
    return true;
  });
}

function dailyInboxItem(item) {
  const id = getOpportunityId(item);
  if (!id) {
    return null;
  }
  const analysis = selectedDocumentAnalysis(item);
  const decision = effectiveDecisionLabel(item);
  const status = dailyInboxStatus(item, analysis, decision);
  return {
    opportunity_id: id,
    status,
    label: dailyInboxStatusLabel(status),
    next_action: dailyInboxNextAction(item, analysis, status, decision),
    days_until_deadline: item.days_until_deadline,
    deadline_label: deadlinePressureText(item)
  };
}

function dailyInboxStatus(item, analysis, decision) {
  const normalized = decisionLabel(decision);
  if (["Skip", "Pass", "Blocked"].includes(normalized)) {
    return "passed";
  }
  if (analysis && analysis.bid_state === "owner_packet_ready") {
    return "ready_for_packet";
  }
  if (analysis && Array.isArray(analysis.agent_tasks) && analysis.agent_tasks.length) {
    return analysis.bid_state === "metadata_intake" ? "get_package" : "resolve_gates";
  }
  if (analysis && analysis.bid_state === "metadata_intake") {
    return "get_package";
  }
  if (normalized === "Review") {
    return "review_fit";
  }
  if (normalized === "Monitor") {
    return "watch";
  }
  return "get_package";
}

function dailyInboxNextAction(item, analysis, status, decision) {
  const complianceDecision = analysis && analysis.compliance_decision;
  if (complianceDecision && complianceDecision.next_action) {
    return complianceDecisionNextAction(complianceDecision);
  }
  const tasks = Array.isArray(analysis && analysis.agent_tasks) ? analysis.agent_tasks : [];
  if (tasks.length && tasks[0].title) {
    return cleanDisplayText(tasks[0].title);
  }
  if (status === "ready_for_packet") {
    return "Prepare bid notes";
  }
  if (status === "get_package") {
    return "Start from city record, then upload or fetch the official package";
  }
  if (status === "resolve_gates") {
    return "Resolve open compliance gates";
  }
  if (status === "review_fit") {
    return "Review scope, capacity, and deadline before assigning estimator time";
  }
  if (status === "watch") {
    return "Keep watching until urgency or fit improves";
  }
  if (["Skip", "Pass", "Blocked"].includes(decisionLabel(decision))) {
    return "Do not spend bid time today";
  }
  return ownerTaskText(item);
}

function dailyInboxSections(items) {
  const order = ["ready_for_packet", "resolve_gates", "get_package", "review_fit", "watch", "passed"];
  return order.map((status) => {
    const count = items.filter((item) => item.status === status).length;
    return { status, label: dailyInboxStatusLabel(status), count };
  }).filter((section) => section.count > 0);
}

function dailyInboxStatusLabel(status) {
  const labels = {
    ready_for_packet: "Ready",
    resolve_gates: "Resolve",
    get_package: "Need Package",
    review_fit: "Review",
    watch: "Watch",
    passed: "Passed"
  };
  return labels[status] || titleCase(humanizeToken(status || "Inbox"));
}

function dailyInboxSort(a, b) {
  const order = {
    ready_for_packet: 0,
    resolve_gates: 1,
    get_package: 2,
    review_fit: 3,
    watch: 4,
    passed: 5
  };
  const leftOrder = order[a.status] ?? 99;
  const rightOrder = order[b.status] ?? 99;
  if (leftOrder !== rightOrder) {
    return leftOrder - rightOrder;
  }
  return deadlineSortValue(a.days_until_deadline) - deadlineSortValue(b.days_until_deadline);
}

function deadlineSortValue(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 9999;
}

function renderOpportunityList(container, items, emptyText) {
  container.className = items.length ? "docket-list" : "docket-list empty-list";
  if (!items.length) {
    container.innerHTML = `<p>${escapeHtml(emptyText)}</p>`;
    return;
  }

  container.innerHTML = items.map((item) => opportunityCard(item)).join("");
  container.querySelectorAll(".opportunity-card").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedOpportunityId = card.dataset.id || "";
      $("approveButton").disabled = !canApproveCurrent();
      renderOwner(state.scan);
      renderEvidence(state.scan);
    });
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        card.click();
      }
    });
  });
}

function opportunityCard(item) {
  const id = getOpportunityId(item);
  const solicitation = item.solicitation || {};
  const selected = id && id === state.selectedOpportunityId ? " selected" : "";
  const deadline = solicitation.submission_deadline || "No deadline listed";
  const dayText = deadlinePressureText(item);
  const decisionOverlay = complianceDecisionForOpportunity(item);
  const internalLabel = effectiveDecisionLabel(item);
  const displayLabel = effectiveOwnerDecisionLabel(item);
  const decisionClass = `decision-${internalLabel.toLowerCase()}`;
  const reason = decisionOverlay ? complianceDecisionReason(decisionOverlay) : queueReason(item);
  const bidLabel = bidRecommendationLabel(item);
  const progressBadge = item._preliminary_match
    ? '<span class="progress-pill">Checking details</span>'
    : "";

  return `
    <article class="opportunity-card ${decisionClass}${selected}" data-id="${escapeHtml(id)}" tabindex="0" role="button" aria-pressed="${selected ? "true" : "false"}">
      <div class="docket-main">
        <div class="card-topline">
          <h4 class="card-title">${escapeHtml(getCompactOpportunityTitle(item, 120))}</h4>
          <div class="card-badges">
            <span class="label-pill ${labelClass(internalLabel)}">${escapeHtml(displayLabel)}</span>
            ${progressBadge}
          </div>
        </div>
        <div class="card-meta">
          <span>Listing ${escapeHtml(id || "pending")}</span>
          <span>Due ${escapeHtml(deadline)}</span>
          <span>${escapeHtml(dayText)}</span>
          ${bidLabel ? `<span>${escapeHtml(bidLabel)}</span>` : ""}
        </div>
        <p class="docket-rationale">${escapeHtml(reason)}</p>
      </div>
    </article>
  `;
}

function renderSelectedOpportunityDetail(item) {
  const container = $("selectedOpportunityDetail");
  if (!container) {
    return;
  }
  if (!item) {
    container.className = "selected-detail empty-list";
    container.innerHTML = "<p>No listing selected. Find matches or choose a city listing.</p>";
    return;
  }

  const solicitation = item.solicitation || {};
  const requirements = getStructuredRequirements(item);
  const trace = normalizedBidFitnessTrace(item, requirements);
  const brief = getOpportunityBrief(item);
  const deadline = solicitation.submission_deadline || "No deadline listed";
  const dayText = deadlinePressureText(item);
  const buyer = [
    solicitation.division,
    solicitation.buyer_name,
    solicitation.buyer_email
  ].filter(Boolean).join(" / ");
  const officialDescription = String(solicitation.description || "").trim();
  const whatThisIs = cleanDisplayText(
    getPlainOpportunitySummary(item) || officialDescription || "Official scope summary is not listed in the feed."
  );
  const blockers = blockerItems(item, trace, brief);
  const blockerText = fullSentenceList(
    blockers,
    "No clear deal-breaker surfaced. Confirm the city listing before spending estimating time.",
    4
  );
  const bidRecommendation = getBidRecommendation(item);
  const pricing = getPricingBreakdown(item);
  const worksheet = getPricingWorksheet(item);
  const bidAmount = worksheet && worksheet.target_bid
    ? formatMoney(worksheet.target_bid)
    : pricing && pricing.recommended_bid
      ? formatMoney(pricing.recommended_bid)
    : bidRecommendation && bidRecommendation.recommended_bid
      ? formatMoney(bidRecommendation.recommended_bid)
    : "Not enough history";
  const bidRange = worksheet && worksheet.low_bid && worksheet.high_bid
    ? `${formatMoney(worksheet.low_bid)}-${formatMoney(worksheet.high_bid)} / ${worksheet.confidence || "Unknown"}`
    : pricing
    ? `${Math.round(Number(pricing.win_probability || 0) * 100)}% win / ${formatMoney(pricing.expected_profit || 0)} EV`
    : bidRangeLabel(bidRecommendation);
  const nextStep = ownerTaskText(item);
  const fit = fitConfidenceText(item, trace);
  const decisionOverlay = complianceDecisionForOpportunity(item);
  const decision = effectiveOwnerDecisionLabel(item);
  const internalLabel = effectiveDecisionLabel(item);
  const sourceLabel = briefSourceLabel(brief);
  const whyUs = fitNarrative(item, trace, requirements, brief);
  const scope = scopeNarrative(item, requirements, brief, whatThisIs);
  const documents = documentItems(item, requirements, brief);
  const documentText = documents.length
    ? humanList(documents)
    : "Confirm the official Toronto package before assigning estimating time.";
  const buyerText = buyer || "Toronto contact not listed";
  const title = getCompactOpportunityTitle(item, 190);
  const portfolioBlock = renderPortfolioDecisionBlock(item);
  const documentUploadBlock = renderDocumentUploadPanel(item);

  container.className = "selected-detail";
  container.innerHTML = `
    <article class="selected-detail-card contract-reader">
      <section class="contract-hero decision-${escapeHtml(internalLabel.toLowerCase())}">
        <div class="contract-hero-copy">
          <span class="label-pill ${labelClass(internalLabel)}">${escapeHtml(decision)}</span>
          <h4>${escapeHtml(title)}</h4>
          <p>${escapeHtml(shortText(scope, 220))}</p>
        </div>
        <div class="contract-next-step">
          <span>Next step</span>
          <strong>${escapeHtml(cleanDisplayText(decisionOverlay ? complianceDecisionNextAction(decisionOverlay) : nextStep))}</strong>
          <em>${escapeHtml(sourceLabel)}</em>
        </div>
      </section>

      <dl class="hero-facts">
        ${renderHeroFact("Due Date", deadline, dayText, "deadline")}
        ${renderHeroFact("Document #", getOpportunityId(item) || "Not listed", solicitation.solicitation_type || "Toronto listing")}
        ${renderHeroFact("Bid Guidance", bidAmount, bidRange || "Pricing engine guidance")}
        ${renderHeroFact("Fit", fit, buyerText, "fit")}
      </dl>

      <div class="quick-read-grid">
        ${renderDecisionBriefBlock("Why Us", whyUs, "primary wide")}
        ${renderDecisionBriefBlock("Scope", whatThisIs)}
        ${renderDecisionBriefBlock("Bid Value", bidRecommendationLanguage(item))}
        ${renderDecisionBriefBlock("Documents", documentText)}
        ${renderDecisionBriefBlock("What To Check", decisionOverlay ? complianceDecisionReason(decisionOverlay) : blockerText, decisionOverlay && decisionOverlay.blocking ? "warning" : blockers.length ? "warning" : "")}
      </div>
      ${documentUploadBlock}
      ${portfolioBlock}
    </article>
  `;
  bindDocumentUploadControl(item);
}

function renderHeroFact(label, value, note = "", modifier = "") {
  return `
    <div class="${modifier ? `hero-fact-${escapeHtml(modifier)}` : ""}">
      <dt>${escapeHtml(label)}</dt>
      <dd>${escapeHtml(value)}</dd>
      ${note ? `<small>${escapeHtml(cleanDisplayText(note))}</small>` : ""}
    </div>
  `;
}

function renderDecisionBriefBlock(label, body, tone = "") {
  const toneClass = String(tone || "")
    .split(/\s+/)
    .filter(Boolean)
    .map((token) => `brief-${token}`)
    .join(" ");
  return `
    <section class="brief-block ${escapeHtml(toneClass)}">
      <span class="selected-detail-label">${escapeHtml(label)}</span>
      <p>${escapeHtml(cleanDisplayText(body))}</p>
    </section>
  `;
}

function renderPortfolioDecisionBlock(item) {
  const decision = item && item.portfolio_decision;
  if (!decision || !decision.decision) {
    return "";
  }
  const engine = portfolioEngineLabel(decision.engine);
  const capacity = decision.capacity_used ? "Uses pursuit capacity" : "No pursuit slot used";
  const facts = [
    ["Decision", decision.decision],
    ["Expected Value", decision.expected_value ? formatMoney(decision.expected_value) : "Not estimated"],
    ["Estimator Time", decision.estimator_hours ? `${number(decision.estimator_hours)} hours` : "Not estimated"],
    ["Engine", engine]
  ];
  const reason = firstItems(decision.reasons || [], 1)[0] || portfolioLanguage(item);
  return `
    <section class="portfolio-decision-block">
      <div>
        <span class="selected-detail-label">Portfolio Decision</span>
        <strong>${escapeHtml(decision.decision)}</strong>
        <p>${escapeHtml(cleanDisplayText(reason))}</p>
      </div>
      <dl>
        ${facts.map(([label, value]) => `
          <div>
            <dt>${escapeHtml(label)}</dt>
            <dd>${escapeHtml(value)}</dd>
          </div>
        `).join("")}
      </dl>
      <em>${escapeHtml(capacity)}</em>
    </section>
  `;
}

function renderDocumentUploadPanel(item) {
  const analysis = selectedDocumentAnalysis(item);
  const summary = analysis && analysis.compliance_summary;
  const rows = complianceRowsForOpportunity(item);
  const document = analysis && analysis.document;
  const acquisition = analysis && analysis.acquisition;
  const acquireBusy = state.documentAcquireBusy;
  const uploadBusy = state.documentUploadBusy;
  const hasDocument = Boolean(document);
  const statusText = documentPanelStatusText(analysis, summary);
  const agentState = analysis ? agentStateLabel(analysis.bid_state) : "";
  const documentText = hasDocument
    ? `${document.filename || "Uploaded PDF"} / ${number(document.size || 0)} bytes${agentState ? ` / ${agentState}` : ""}`
    : acquisition
      ? `${acquisition.source_label || "Open Data"} / ${agentState || "City record only"}`
      : "No official package checked yet";
  return `
    <section class="document-upload-panel">
      <div class="document-upload-head">
        <div>
          <span class="selected-detail-label">${escapeHtml(hasDocument ? "Official PDF" : analysis ? "City Record Intake" : "Official Package")}</span>
          <strong>${escapeHtml(statusText)}</strong>
          <p>${escapeHtml(documentText)}</p>
        </div>
        <div class="document-upload-actions">
          <button id="startFromCityRecordButton" class="secondary-action" type="button" ${acquireBusy ? "disabled" : ""}>
            ${escapeHtml(acquireBusy ? "Checking..." : acquisition && !hasDocument ? "Refresh Intake" : "Start Intake")}
          </button>
          <input id="documentUploadInput" class="sr-only" type="file" accept="application/pdf">
          <input id="evidenceUploadInput" class="sr-only" type="file">
          <button id="analyzeDocumentButton" class="secondary-action" type="button" ${uploadBusy ? "disabled" : ""}>
            ${escapeHtml(uploadBusy ? "Analyzing..." : analysis ? "Analyze New PDF" : "Analyze PDF")}
          </button>
        </div>
      </div>
      ${acquisition && !hasDocument ? renderAcquisitionGuidance(acquisition) : ""}
      ${analysis ? renderAgentTaskQueue(analysis) : ""}
      ${analysis ? renderSubmissionManifestCard(analysis.submission_manifest, analysis.submission_manifest_summary) : ""}
      ${analysis ? renderComplianceMatrixPreview(rows, analysis) : ""}
    </section>
  `;
}

function documentPanelStatusText(analysis, summary) {
  if (!analysis) {
    return "Start from the city record, then fetch or upload the official package.";
  }
  const acquisition = analysis.acquisition || null;
  if (acquisition && !analysis.document) {
    return acquisition.message || "City record loaded; official package required before compliance clearance.";
  }
  return complianceSummaryText(summary);
}

function renderAcquisitionGuidance(acquisition) {
  const guidance = acquisition && acquisition.guidance ? acquisition.guidance : {};
  const instructions = Array.isArray(guidance.instructions) ? guidance.instructions : [];
  const expected = Array.isArray(guidance.expected_documents) ? guidance.expected_documents : [];
  const candidates = Array.isArray(guidance.candidate_public_package_urls) ? guidance.candidate_public_package_urls : [];
  const portalUrl = guidance.portal_url || acquisition.portal_url || "";
  return `
    <div class="acquisition-guidance">
      <div>
        <span>${escapeHtml(humanizeToken(acquisition.status || "package_required"))}</span>
        <strong>${escapeHtml(cleanDisplayText(guidance.next_step || acquisition.next_step || "Upload official package"))}</strong>
        <p>${escapeHtml(cleanDisplayText(guidance.reason || acquisition.message || ""))}</p>
      </div>
      ${portalUrl ? `<a href="${escapeHtml(portalUrl)}" target="_blank" rel="noreferrer">Open Portal</a>` : ""}
      ${instructions.length ? `<ul>${instructions.slice(0, 4).map((item) => `<li>${escapeHtml(cleanDisplayText(item))}</li>`).join("")}</ul>` : ""}
      ${expected.length || candidates.length ? `
        <p>${escapeHtml(cleanDisplayText([
          expected.length ? `Expected: ${expected.slice(0, 4).join(", ")}` : "",
          candidates.length ? `${candidates.length} direct PDF candidate${candidates.length === 1 ? "" : "s"} found` : ""
        ].filter(Boolean).join(" / ")))}</p>
      ` : ""}
    </div>
  `;
}

function renderAgentTaskQueue(analysis) {
  const tasks = Array.isArray(analysis && analysis.agent_tasks) ? analysis.agent_tasks : [];
  if (!tasks.length) {
    const ready = analysis && analysis.bid_state === "owner_packet_ready";
    return `
      <div class="agent-task-queue agent-task-${ready ? "ready" : "review"}">
        <div>
          <span class="selected-detail-label">Agent Next Actions</span>
          <strong>${escapeHtml(ready ? "No open deterministic tasks" : "No tasks generated")}</strong>
          <p>${escapeHtml(ready ? "The server state allows bid notes to be prepared." : "Review the PDF manually before preparing bid notes.")}</p>
        </div>
      </div>
    `;
  }
  return `
    <div class="agent-task-queue">
      <div class="agent-task-head">
        <div>
          <span class="selected-detail-label">Agent Next Actions</span>
          <strong>${escapeHtml(`${tasks.length} deterministic task${tasks.length === 1 ? "" : "s"} blocking bid notes`)}</strong>
        </div>
        <em>${escapeHtml(agentStateLabel(analysis.bid_state))}</em>
      </div>
      <div class="agent-task-list">
        ${tasks.map((task) => renderAgentTask(task)).join("")}
      </div>
    </div>
  `;
}

function renderSubmissionManifestCard(manifest, summary) {
  const rows = Array.isArray(manifest) ? manifest : [];
  if (!rows.length) {
    return "";
  }
  const counts = summary || {};
  const openRows = rows.filter((row) => row && row.status !== "ready");
  const displayRows = firstItems(openRows.length ? openRows : rows, 4);
  const requiredOpen = Number(counts.required_open || 0);
  const headline = requiredOpen
    ? `${number(requiredOpen)} required submission item${requiredOpen === 1 ? "" : "s"} still open`
    : "Submission checklist is ready";
  const detail = counts.next_item
    ? `Next: ${counts.next_item}`
    : `${number(counts.ready || 0)}/${number(counts.total || rows.length)} ready`;
  return `
    <div class="submission-manifest-card">
      <div class="submission-manifest-head">
        <div>
          <span class="selected-detail-label">Submission Readiness</span>
          <strong>${escapeHtml(headline)}</strong>
          <p>${escapeHtml(cleanDisplayText(detail))}</p>
        </div>
        <em>${escapeHtml(counts.ready_for_submission ? "Ready" : "Open")}</em>
      </div>
      <ul>
        ${displayRows.map((row) => `
          <li class="manifest-${escapeHtml(row.status || "review")}">
            <span>${escapeHtml(humanizeToken(row.status || "review"))}</span>
            <strong>${escapeHtml(cleanDisplayText(row.label || row.item_type || "Submission item"))}</strong>
            <small>${escapeHtml(cleanDisplayText(shortText(row.reason || "", 120)))}</small>
          </li>
        `).join("")}
      </ul>
    </div>
  `;
}

function renderAgentTask(task) {
  const citation = task.citation || {};
  const page = task.task_type === "acquire_official_package"
    ? "City Record"
    : citation.page ? `p. ${citation.page}` : "source PDF";
  const options = Array.isArray(task.resolution_options) ? task.resolution_options : [];
  const pricing = task.pricing_worksheet && typeof task.pricing_worksheet === "object" ? task.pricing_worksheet : {};
  const missingPricingInputs = Array.isArray(pricing.missing_inputs) ? pricing.missing_inputs : [];
  const pricingLine = task.task_type === "approve_pricing" && pricing.target_bid
    ? `Target ${formatMoney(pricing.target_bid)} / ${formatMoney(pricing.low_bid || 0)}-${formatMoney(pricing.high_bid || 0)}`
    : task.task_type === "record_pricing_input" && missingPricingInputs.length
      ? missingPricingInputs.map((item) => cleanDisplayText(item.reason || item.input_type || "Pricing input needed")).join(" ")
    : "";
  const taskActions = task.task_type === "approve_pricing" && pricing.target_bid
    ? `
      <button class="approve-pricing-button" type="button" ${state.pricingApproveBusy ? "disabled" : ""}>
        ${escapeHtml(state.pricingApproveBusy ? "Approving..." : "Approve Target")}
      </button>
    `
    : task.task_type === "record_pricing_input" && missingPricingInputs.length
      ? missingPricingInputs.map((item) => `
        <button class="record-pricing-input-button" type="button" data-input-type="${escapeHtml(item.input_type || "")}" ${state.pricingApproveBusy ? "disabled" : ""}>
          ${escapeHtml(shortText(`Add ${humanizeToken(item.input_type || "input")}`, 22))}
        </button>
      `).join("")
    : task.task_type === "approve_pricing"
      ? '<span class="agent-task-manual">Pricing blocked</span>'
    : options.length
      ? options.map((option) => `
        <button class="resolve-compliance-button" type="button" data-requirement-id="${escapeHtml(task.requirement_id || "")}" data-resolution-type="${escapeHtml(option.type || "")}" ${state.complianceResolveBusy === task.requirement_id ? "disabled" : ""}>
          ${escapeHtml(shortText(option.label || option.type || "Resolve", 22))}
        </button>
      `).join("")
      : '<span class="agent-task-manual">Upload PDF</span>';
  return `
    <article class="agent-task ${task.blocking ? "agent-task-blocking" : "agent-task-review"}">
      <div>
        <span>${escapeHtml(task.blocking ? "Hard Stop" : "Review Gate")}</span>
        <strong>${escapeHtml(cleanDisplayText(task.title || "Resolve requirement"))}</strong>
        <p>${escapeHtml(cleanDisplayText([task.detail || "", pricingLine].filter(Boolean).join(" ")))}</p>
      </div>
      <small>${escapeHtml(page)}</small>
      <div class="agent-task-actions">
        ${taskActions}
      </div>
    </article>
  `;
}

function renderComplianceMatrixPreview(rows, analysis = null) {
  const safeRows = Array.isArray(rows) ? rows : [];
  if (!safeRows.length) {
    const text = analysis && analysis.bid_state === "metadata_intake"
      ? "No PDF compliance rows yet. The city record is loaded, but the official package is still required."
      : "No compliance rows were extracted from this PDF.";
    return `<div class="compliance-empty"><p>${escapeHtml(text)}</p></div>`;
  }
  return `
    <div class="compliance-matrix">
      ${safeRows.map((row) => {
        const citation = row.citation || {};
        const page = citation.page ? `p. ${citation.page}` : "page not listed";
        const rowState = complianceRowState(row);
        const action = complianceResolutionAction(row);
        const evidenceNeeded = (row.evidence_needed || []).join(", ");
        const attachedEvidence = (row.uploaded_evidence || []).map(complianceEvidenceLabel).filter(Boolean).join(", ");
        const evidenceLine = evidenceNeeded
          ? `Evidence needed: ${evidenceNeeded}`
          : attachedEvidence ? `Evidence: ${attachedEvidence}` : "";
        return `
          <article class="compliance-row compliance-${escapeHtml(rowState.key)}">
            <div>
              <span>${escapeHtml(titleCase(humanizeToken(row.category || "requirement")))}</span>
              <strong>${escapeHtml(cleanDisplayText(shortText(row.requirement || "Requirement", 150)))}</strong>
              ${evidenceLine ? `<p>${escapeHtml(cleanDisplayText(shortText(evidenceLine, 180)))}</p>` : ""}
            </div>
            <em>${escapeHtml(rowState.label)}</em>
            <small>${escapeHtml(page)}</small>
            ${action ? `
              <button class="resolve-compliance-button" type="button" data-requirement-id="${escapeHtml(row.requirement_id || "")}" data-resolution-type="${escapeHtml(action.type)}" ${state.complianceResolveBusy === row.requirement_id ? "disabled" : ""}>
                ${escapeHtml(action.label)}
              </button>
            ` : ""}
            ${!row.resolved ? `
              <button class="upload-evidence-button" type="button" data-requirement-id="${escapeHtml(row.requirement_id || "")}" data-category="${escapeHtml(row.category || "")}" data-requirement="${escapeHtml(row.requirement || "")}" ${state.evidenceUploadBusy === row.requirement_id ? "disabled" : ""}>
                ${escapeHtml(state.evidenceUploadBusy === row.requirement_id ? "Uploading..." : "Upload Evidence")}
              </button>
            ` : ""}
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function bindDocumentUploadControl(item) {
  const input = $("documentUploadInput");
  const evidenceInput = $("evidenceUploadInput");
  const button = $("analyzeDocumentButton");
  const acquireButton = $("startFromCityRecordButton");
  if (!input || !evidenceInput || !button || !acquireButton || !item) {
    return;
  }
  acquireButton.addEventListener("click", acquireSelectedOpportunityDocuments);
  button.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (file) {
      analyzeSelectedDocument(file);
    }
  });
  evidenceInput.addEventListener("change", () => {
    const file = evidenceInput.files && evidenceInput.files[0];
    const target = state.evidenceAttachTarget;
    evidenceInput.value = "";
    if (file && target) {
      uploadEvidenceForRequirement(file, target);
    }
  });
  document.querySelectorAll(".resolve-compliance-button").forEach((resolveButton) => {
    resolveButton.addEventListener("click", () => {
      resolveComplianceRequirement(
        resolveButton.dataset.requirementId || "",
        resolveButton.dataset.resolutionType || ""
      );
    });
  });
  document.querySelectorAll(".approve-pricing-button").forEach((pricingButton) => {
    pricingButton.addEventListener("click", approvePricingForCurrent);
  });
  document.querySelectorAll(".record-pricing-input-button").forEach((inputButton) => {
    inputButton.addEventListener("click", () => {
      recordPricingInputForCurrent(inputButton.dataset.inputType || "");
    });
  });
  document.querySelectorAll(".upload-evidence-button").forEach((uploadButton) => {
    uploadButton.addEventListener("click", () => {
      state.evidenceAttachTarget = {
        requirementId: uploadButton.dataset.requirementId || "",
        category: uploadButton.dataset.category || "",
        requirement: uploadButton.dataset.requirement || ""
      };
      evidenceInput.click();
    });
  });
}

async function acquireSelectedOpportunityDocuments() {
  const selected = findSelectedOpportunity();
  if (!selected) {
    showToast("Select a city listing first.");
    return;
  }

  const opportunityId = getOpportunityId(selected);
  state.documentAcquireBusy = true;
  renderOwner(state.scan);
  showToast("Checking city record");
  try {
    const profile = currentProfile();
    const result = await apiPost("/api/documents/acquire", {
      profile_id: profile.profile_id,
      business_profile: profile,
      opportunity_id: opportunityId
    });
    state.documentAnalyses[opportunityId] = result;
    const acquisition = result.acquisition || {};
    showToast(result.document ? "Official package analyzed" : acquisition.status === "fetch_failed" ? "Package fetch failed" : "City record intake ready");
  } catch (error) {
    showToast(error.message);
  } finally {
    state.documentAcquireBusy = false;
    renderOwner(state.scan);
    $("approveButton").disabled = !canApproveCurrent();
  }
}

async function analyzeSelectedDocument(file) {
  const selected = findSelectedOpportunity();
  if (!selected) {
    showToast("Select a city listing first.");
    return;
  }
  if (!String(file.name || "").toLowerCase().endsWith(".pdf")) {
    showToast("Upload a PDF file.");
    return;
  }

  const opportunityId = getOpportunityId(selected);
  state.documentUploadBusy = true;
  renderOwner(state.scan);
  showToast("Analyzing official PDF");
  try {
    const profile = currentProfile();
    const contentBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const result = await apiPost("/api/documents/analyze", {
      profile_id: profile.profile_id,
      business_profile: profile,
      opportunity_id: opportunityId,
      filename: file.name,
      content_base64: contentBase64
    });
    state.documentAnalyses[opportunityId] = result;
    showToast("Compliance matrix ready");
  } catch (error) {
    showToast(error.message);
  } finally {
    state.documentUploadBusy = false;
    renderOwner(state.scan);
    $("approveButton").disabled = !canApproveCurrent();
  }
}

async function resolveComplianceRequirement(requirementId, resolutionType) {
  const analysis = selectedDocumentAnalysis();
  const selected = findSelectedOpportunity();
  if (!analysis || !selected) {
    showToast("Analyze a PDF before resolving compliance items.");
    return;
  }
  state.complianceResolveBusy = requirementId;
  renderOwner(state.scan);
  try {
    const result = await apiPost("/api/compliance/resolve", {
      analysis_id: analysis.analysis_id,
      requirement_id: requirementId,
      resolution_type: resolutionType
    });
    state.documentAnalyses[getOpportunityId(selected)] = result;
    showToast("Compliance item resolved");
  } catch (error) {
    showToast(error.message);
  } finally {
    state.complianceResolveBusy = "";
    renderOwner(state.scan);
    $("approveButton").disabled = !canApproveCurrent();
  }
}

async function approvePricingForCurrent() {
  const analysis = selectedDocumentAnalysis();
  const selected = findSelectedOpportunity();
  if (!analysis || !selected) {
    showToast("Analyze a PDF before approving pricing.");
    return;
  }
  state.pricingApproveBusy = true;
  renderOwner(state.scan);
  try {
    const result = await apiPost("/api/pricing/approve", {
      analysis_id: analysis.analysis_id,
      approved_by: "Estimator"
    });
    state.documentAnalyses[getOpportunityId(selected)] = result;
    showToast("Target bid approved");
  } catch (error) {
    showToast(error.message);
  } finally {
    state.pricingApproveBusy = false;
    renderOwner(state.scan);
    $("approveButton").disabled = !canApproveCurrent();
  }
}

async function recordPricingInputForCurrent(inputType) {
  const analysis = selectedDocumentAnalysis();
  const selected = findSelectedOpportunity();
  if (!analysis || !selected) {
    showToast("Analyze a PDF before adding pricing inputs.");
    return;
  }
  const label = humanizeToken(inputType || "pricing input");
  const rawValue = window.prompt(`Enter ${label}`);
  if (rawValue === null) {
    return;
  }
  const value = Number(String(rawValue).replace(/[$,]/g, "").trim());
  if (!Number.isFinite(value) || value <= 0) {
    showToast("Enter a positive number.");
    return;
  }
  state.pricingApproveBusy = true;
  renderOwner(state.scan);
  try {
    const result = await apiPost("/api/pricing/input", {
      analysis_id: analysis.analysis_id,
      input_type: inputType,
      value,
      unit: inputType === "quantity" || inputType === "unit_count" ? "units" : "CAD",
      created_by: "Estimator"
    });
    state.documentAnalyses[getOpportunityId(selected)] = result;
    showToast("Pricing input recorded");
  } catch (error) {
    showToast(error.message);
  } finally {
    state.pricingApproveBusy = false;
    renderOwner(state.scan);
    $("approveButton").disabled = !canApproveCurrent();
  }
}

async function uploadEvidenceForRequirement(file, target) {
  const analysis = selectedDocumentAnalysis();
  const selected = findSelectedOpportunity();
  if (!analysis || !selected) {
    showToast("Analyze a PDF before attaching evidence.");
    return;
  }
  const requirementId = target.requirementId || "";
  if (!requirementId) {
    showToast("Select a compliance requirement first.");
    return;
  }
  state.evidenceUploadBusy = requirementId;
  renderOwner(state.scan);
  try {
    const profile = currentProfile();
    const contentBase64 = arrayBufferToBase64(await file.arrayBuffer());
    const uploaded = await apiPost("/api/evidence/upload", {
      profile_id: profile.profile_id,
      business_profile: profile,
      filename: file.name,
      label: file.name,
      evidence_type: evidenceTypeForCategory(target.category),
      capability_tags: [target.category, target.requirement],
      content_base64: contentBase64
    });
    const evidenceId = uploaded && uploaded.evidence && uploaded.evidence.evidence_id;
    if (!evidenceId) {
      throw new Error("Evidence upload did not return an evidence id.");
    }
    const result = await apiPost("/api/compliance/attach-evidence", {
      analysis_id: analysis.analysis_id,
      requirement_id: requirementId,
      evidence_id: evidenceId
    });
    state.documentAnalyses[getOpportunityId(selected)] = result;
    showToast("Evidence attached");
  } catch (error) {
    showToast(error.message);
  } finally {
    state.evidenceUploadBusy = "";
    state.evidenceAttachTarget = null;
    renderOwner(state.scan);
    $("approveButton").disabled = !canApproveCurrent();
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

function bidRangeLabel(recommendation) {
  if (!recommendation) {
    return "";
  }
  if (recommendation.low_bid && recommendation.high_bid && recommendation.low_bid !== recommendation.high_bid) {
    return `${formatMoney(recommendation.low_bid)}-${formatMoney(recommendation.high_bid)}`;
  }
  if (recommendation.confidence) {
    return `${recommendation.confidence} confidence`;
  }
  return "";
}

function fitNarrative(item, trace, requirements, brief) {
  const briefFit = cleanDisplayText(String((brief && brief.fit_reason) || "").trim());
  if (briefFit && briefFit.length > 36) {
    return briefFit;
  }

  const profile = currentProfile();
  const services = firstItems((requirements && requirements.services) || item.matched_terms || [], 4);
  const history = item.historical || {};
  const assessment = getCapacityAssessment(item);
  const parts = [];
  if (services.length) {
    parts.push(`${compactCompanyName(profile.name) || "This business"} already works in ${humanList(services)}, which matches the core scope in this listing.`);
  } else {
    parts.push(`${compactCompanyName(profile.name) || "This business"} matches the selected ${compactProfileLabel(profile)} lane for this listing.`);
  }
  if (history.similar_count) {
    const median = history.award_median ? ` with a typical award around ${formatMoney(history.award_median)}` : "";
    parts.push(`The system found ${number(history.similar_count)} similar Toronto award(s)${median}, so this is grounded in real purchasing history rather than keyword overlap.`);
  }
  if (assessment) {
    parts.push(`Capacity check: ${assessment.pursuit_load} pursuit load, ${String(assessment.response_capacity || "").toLowerCase()}, and ${String(assessment.execution_capacity || "").toLowerCase()}.`);
  }
  const positive = firstItems((trace && trace.positiveSignals) || [], 1)[0];
  if (positive) {
    parts.push(ownerText(positive));
  }
  return cleanDisplayText(parts.join(" "));
}

function scopeNarrative(item, requirements, brief, fallback) {
  const summary = cleanDisplayText(String((brief && brief.owner_summary) || "").trim());
  if (summary) {
    return summary;
  }
  const services = firstItems((requirements && requirements.services) || item.matched_terms || [], 4);
  const solicitation = item.solicitation || {};
  if (services.length) {
    return `City work involving ${humanList(services)}${solicitation.division ? ` for ${solicitation.division}` : ""}.`;
  }
  return fallback;
}

function renderDossierBucket(label, items, emptyText) {
  const safeItems = firstItems(uniqueTextItems(textItems(items)), 6);
  return `
    <section class="dossier-bucket">
      <span class="selected-detail-label">${escapeHtml(label)}</span>
      ${safeItems.length
    ? `<ul>${safeItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p>${escapeHtml(emptyText)}</p>`}
    </section>
  `;
}

function renderDecisionGate(item, result) {
  const gateStatus = $("gateStatus");
  const checklist = $("decisionGateChecklist");
  if (!gateStatus || !checklist) {
    return;
  }
  if (!item) {
    gateStatus.textContent = "Waiting";
    checklist.className = "gate-checklist empty-list";
    checklist.innerHTML = "<p>Find matches to see whether this looks ready to bid.</p>";
    return;
  }

  const requirements = getStructuredRequirements(item);
  const brief = getOpportunityBrief(item);
  const assessment = getCapacityAssessment(item);
  const source = getSourceLinks(item);
  const trace = normalizedBidFitnessTrace(item, requirements);
  const capacityWarnings = uniqueTextItems([
    ...trace.hardBlockers,
    ...capacityWarningItems(item),
    ...textItems(brief && (brief.blockers || brief.missing_items))
  ]);
  const documents = documentItems(item, requirements, brief);
  const sourceReady = Boolean(source && !source.is_sample_record);
  const capacityReady = !capacityWarnings.length;
  const documentsReady = Boolean(documents.length || sourceReady);
  const documentAnalysis = selectedDocumentAnalysis(item);
  const complianceSummary = documentAnalysis && documentAnalysis.compliance_summary;
  const complianceRows = complianceRowsForOpportunity(item);
  const complianceReady = Boolean(
    documentAnalysis
      && complianceRows.length
      && complianceSummary
      && complianceSummary.ready_to_prepare
      && documentAnalysis.bid_state === "owner_packet_ready"
  );
  const complianceDetail = documentAnalysis
    ? complianceSummaryText(complianceSummary)
    : "Start from the city record or upload the official package";
  const deadlineReady = item.days_until_deadline === undefined || item.days_until_deadline === null
    ? false
    : item.days_until_deadline >= 0;
  const checks = [
    ["Deadline", deadlineReady ? deadlinePressureText(item) : "Deadline missing or expired", deadlineReady],
    ["Team Capacity", capacityReady ? (assessment && assessment.recommended_action ? cleanDisplayText(assessment.recommended_action) : "No capacity problem found") : shortText(cleanDisplayText(capacityWarnings[0]), 110), capacityReady],
    ["City Listing", documentsReady ? shortText(documents.length ? documents.slice(0, 2).map(cleanDisplayText).join(", ") : "Listing page available", 110) : "Open the city listing before bid work", documentsReady],
    ["PDF Compliance", shortText(complianceDetail, 120), complianceReady]
  ];
  const approvedChecks = checks.filter(([, , ok]) => ok).length;
  gateStatus.textContent = `${approvedChecks}/${checks.length} ready`;
  gateStatus.className = `count-pill ${approvedChecks === checks.length ? "gate-ready" : "gate-review"}`;
  checklist.className = "gate-checklist";
  checklist.innerHTML = `
    <div class="gate-owner-task">
      <span>Next step</span>
      <strong>${escapeHtml(cleanDisplayText(ownerTaskText(item)))}</strong>
    </div>
    <ol>
      ${checks.map(([name, detail, ok]) => `
        <li class="${ok ? "gate-ok" : "gate-warn"}">
          <span>${escapeHtml(name)}</span>
          <strong>${escapeHtml(detail)}</strong>
        </li>
      `).join("")}
    </ol>
  `;
}

function metricStatCard(label, value, detail = "") {
  return `
    <article class="scorecard-item">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value || "0"))}</strong>
      ${detail ? `<p>${escapeHtml(String(detail))}</p>` : ""}
    </article>
  `;
}

function topStageSummary(timings) {
  const entries = Object.entries(timings || {})
    .map(([stage, ms]) => [stage, Number(ms || 0)])
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    return "No stage timing yet";
  }
  const [stage, ms] = entries[0];
  return `${titleCase(humanizeToken(stage))}: ${number(ms)} ms`;
}

function dataSourceSummary(metrics) {
  const sources = metrics.data_sources || {};
  const values = Object.values(sources).map((value) => String(value || ""));
  if (!values.length) {
    return "No sources loaded";
  }
  return firstItems(values, 2).join(" / ");
}

function pricedOpportunities(result) {
  const items = [
    ...((result && result.top_opportunities) || []),
    ...((result && result.watchlist) || []),
    ...((result && result.all_evaluated) || [])
  ];
  const seen = new Set();
  return items.filter((item) => {
    const pricing = item && item.pricing_breakdown;
    const id = getOpportunityId(item);
    if (!pricing || !pricing.recommended_bid || seen.has(id)) {
      return false;
    }
    seen.add(id);
    return true;
  });
}

function percent(value) {
  const numeric = Number(value || 0);
  return `${Math.round(numeric * 100)}%`;
}

function safeRatio(numerator, denominator) {
  const bottom = Number(denominator || 0);
  return bottom ? Number(numerator || 0) / bottom : 0;
}

function averageNumber(values) {
  const clean = values.map(Number).filter((value) => Number.isFinite(value));
  return clean.length ? sumNumber(clean) / clean.length : 0;
}

function medianNumber(values) {
  const clean = values.map(Number).filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!clean.length) {
    return 0;
  }
  const middle = Math.floor(clean.length / 2);
  return clean.length % 2 ? clean[middle] : (clean[middle - 1] + clean[middle]) / 2;
}

function minNumber(values) {
  const clean = values.map(Number).filter((value) => Number.isFinite(value));
  return clean.length ? Math.min(...clean) : 0;
}

function maxNumber(values) {
  const clean = values.map(Number).filter((value) => Number.isFinite(value));
  return clean.length ? Math.max(...clean) : 0;
}

function sumNumber(values) {
  return values.map(Number).filter((value) => Number.isFinite(value)).reduce((sum, value) => sum + value, 0);
}

function renderPipeline(metrics, result = {}) {
  const timings = metrics.stage_timings_ms || {};
  const localMs = metrics.runtime_ms || 0;
  const modelMode = metrics.market_model_mode || "not scored";
  const valueMode = metrics.value_model_mode || "historical_average";
  const stageCount = Object.keys(timings).length;
  const sourceCount = Object.keys(metrics.data_sources || {}).length;
  const cards = [
    ["Rows Scanned", number((metrics.solicitations_loaded || 0) + (metrics.awards_loaded || 0)), `${number(metrics.solicitations_loaded)} listings / ${number(metrics.awards_loaded)} awards`],
    ["Local Runtime", `${number(localMs)} ms`, `${number(metrics.records_per_second)} records/sec`],
    ["Pipeline Stages", number(stageCount), topStageSummary(timings)],
    ["Data Sources", number(sourceCount), dataSourceSummary(metrics)],
    ["Market Model", modelMode, `${number(metrics.market_model_examples)} examples / P@10 ${number(metrics.market_model_precision_at_10)}`],
    ["Value Model", valueMode, `MAE ${formatMoney(metrics.value_model_mae || 0)} / MAPE ${percent(metrics.value_model_mape)}`],
    ["RAG", metrics.rag_mode || "not retrieved", `${number((result.insight_scorecard || {}).similar_awards_grounded)} analog-grounded listings`],
    ["Shortlist Rate", percent(metrics.shortlist_reduction_ratio), `${number(metrics.top_candidate_count)} top / ${number(metrics.rejected_count)} filtered`],
    ["Bid Briefs", number(metrics.briefs_generated), `${number(metrics.model_calls_avoided)} low-fit listings avoided`]
  ];

  $("pipelineDetails").className = "scorecard-grid";
  $("pipelineDetails").innerHTML = cards.map(([label, value, detail]) => metricStatCard(label, value, detail)).join("");
}

function renderDecisionProofCard(item) {
  const requirements = getStructuredRequirements(item);
  const trace = normalizedBidFitnessTrace(item, requirements);
  const brief = getOpportunityBrief(item);
  const solicitation = item.solicitation || {};
  const internalLabel = decisionLabel(item.label);
  const decision = ownerDecisionLabel(item.label);
  const title = getCompactOpportunityTitle(item, 120);
  const bidLabel = bidRecommendationLabel(item) || "Bid value not estimated";
  const why = internalLabel === "Skip"
    ? fullSentenceList(blockerItems(item, trace, brief), "This listing is probably not worth bid time.", 3)
    : fitNarrative(item, trace, requirements, brief);
  const check = internalLabel === "Pursue"
    ? ownerTaskText(item)
    : fullSentenceList(blockerItems(item, trace, brief), ownerTaskText(item), 2);
  return `
    <article class="decision-proof-card decision-${escapeHtml(internalLabel.toLowerCase())}">
      <div class="decision-proof-head">
        <div>
          <span class="label-pill ${labelClass(internalLabel)}">${escapeHtml(decision)}</span>
          <h4>${escapeHtml(title)}</h4>
        </div>
        <strong>${escapeHtml(bidLabel)}</strong>
      </div>
      <dl class="decision-proof-meta">
        <div><dt>Document</dt><dd>${escapeHtml(getOpportunityId(item) || "Not listed")}</dd></div>
        <div><dt>Due</dt><dd>${escapeHtml(solicitation.submission_deadline || "Not listed")}</dd></div>
        <div><dt>Status</dt><dd>${escapeHtml(deadlinePressureText(item))}</dd></div>
      </dl>
      <section>
        <span>Why this decision</span>
        <p>${escapeHtml(cleanDisplayText(why))}</p>
      </section>
      <section>
        <span>What to check next</span>
        <p>${escapeHtml(cleanDisplayText(check))}</p>
      </section>
    </article>
  `;
}

function renderPricingStats(result) {
  const priced = pricedOpportunities(result);
  const container = $("skippedExamples");
  container.className = "scorecard-grid";
  if (!priced.length) {
    container.className = "scorecard-grid empty-list";
    container.innerHTML = "<p>Pricing stats appear after the value model runs.</p>";
    return;
  }

  const marketRefs = priced.map((item) => Number(item.pricing_breakdown.market_reference || 0)).filter(Boolean);
  const recommended = priced.map((item) => Number(item.pricing_breakdown.recommended_bid || 0)).filter(Boolean);
  const costs = priced.map((item) => Number(item.pricing_breakdown.estimated_cost || 0)).filter(Boolean);
  const expectedProfits = priced.map((item) => Number(item.pricing_breakdown.expected_profit || 0)).filter(Boolean);
  const winRates = priced.map((item) => Number(item.pricing_breakdown.win_probability || 0)).filter(Boolean);
  const contingencies = priced.map((item) => Number(item.pricing_breakdown.contingency_rate || 0)).filter(Boolean);
  const margins = priced.map((item) => Number(item.pricing_breakdown.margin_rate || 0)).filter(Boolean);
  const complexity = priced.map((item) => Number(item.pricing_breakdown.complexity_score || 0)).filter(Boolean);
  const candidateCount = priced.reduce((sum, item) => sum + ((item.pricing_breakdown.candidate_bids || []).length || 0), 0);
  const cards = [
    ["Priced Listings", number(priced.length), `${number(candidateCount)} candidate bids tested`],
    ["Market Ref", formatMoney(medianNumber(marketRefs)), `${formatMoney(minNumber(marketRefs))}-${formatMoney(maxNumber(marketRefs))}`],
    ["Recommended", formatMoney(medianNumber(recommended)), `${formatMoney(minNumber(recommended))}-${formatMoney(maxNumber(recommended))}`],
    ["Estimated Cost", formatMoney(medianNumber(costs)), `${formatMoney(minNumber(costs))}-${formatMoney(maxNumber(costs))}`],
    ["Expected Profit", formatMoney(medianNumber(expectedProfits)), `${formatMoney(sumNumber(expectedProfits))} total`],
    ["Win Rate", percent(averageNumber(winRates)), `${percent(minNumber(winRates))}-${percent(maxNumber(winRates))}`],
    ["Contingency", percent(averageNumber(contingencies)), `${percent(minNumber(contingencies))}-${percent(maxNumber(contingencies))}`],
    ["Target Margin", percent(averageNumber(margins)), `${percent(minNumber(margins))}-${percent(maxNumber(margins))}`],
    ["Complexity", percent(averageNumber(complexity)), `${percent(minNumber(complexity))}-${percent(maxNumber(complexity))}`]
  ];
  container.innerHTML = cards.map(([label, value, detail]) => metricStatCard(label, value, detail)).join("");
}

function renderScorecard(result) {
  const metrics = result.metrics || {};
  const scorecard = result.insight_scorecard || result.scorecard || {};
  const container = $("scorecardDetails");
  const hasScorecard = Object.keys(scorecard).length > 0 || Object.keys(metrics).length > 0;
  $("scorecardStatus").textContent = hasScorecard ? "Ready" : "Waiting";

  if (!hasScorecard) {
    container.className = "scorecard-grid empty-list";
    container.innerHTML = "<p>Find matches to see validation stats.</p>";
    return;
  }

  container.className = "scorecard-grid";
  const priced = pricedOpportunities(result);
  const cards = [
    ["Historical Fits", number(scorecard.realistic_historical_opportunities), `${number(scorecard.similar_awards_grounded)} analog-grounded`],
    ["Award Range", scorecard.similar_award_range ? shortText(scorecard.similar_award_range, 42) : "Not ready", `${number((scorecard.similar_award_examples || []).length)} examples`],
    ["Model Lift", `${number(metrics.market_model_top_decile_lift)}x`, `precision@10 ${number(metrics.market_model_precision_at_10)}`],
    ["Training Rows", number(metrics.market_model_examples), `${number(metrics.market_model_positive_examples)} positives`],
    ["Value Error", percent(metrics.value_model_mape), `MAE ${formatMoney(metrics.value_model_mae || 0)}`],
    ["Runtime Path", runtimePathLabel(metrics), runtimePathDetail(metrics)],
    ["Portfolio", portfolioEngineLabel(metrics.portfolio_mode), portfolioModeDetail(metrics)],
    ["Bid Briefs", number(metrics.briefs_generated), metrics.brief_mode || "deterministic_bid_brief"],
    ["Local Speed", number(metrics.records_per_second), "records/sec"],
    ["Pricing Coverage", percent(safeRatio(priced.length, (result.top_opportunities || []).length + (result.watchlist || []).length)), `${number(priced.length)} priced`]
  ];
  container.innerHTML = cards.map(([label, value, detail]) => metricStatCard(label, value, detail)).join("");
}

function renderInsightOpportunityCard(scorecard) {
  const best = scorecard.best_current_opportunity || {};
  if (!hasDisplayValue(best) || !best.document_number) {
    return "";
  }
  const title = shortText(best.title || "Current city listing", 150);
  const meta = [
    ownerDecisionLabel(best.label),
    best.division,
    best.deadline ? `Due ${best.deadline}` : "",
    best.award_range
  ].filter(Boolean).join(" | ");
  const reason = best.decision_reason || "Top current listing from the local fit check.";
  return `
    <article class="scorecard-item wide insight-opportunity">
      <span>Best Current Match</span>
      <strong>${escapeHtml(best.document_number)} - ${escapeHtml(title)}</strong>
      <p>${escapeHtml(meta || "Top listing from this search")}</p>
      <ul class="proof-list">
        <li>${escapeHtml(shortText(ownerText(reason), 190))}</li>
        ${firstItems(best.matched_terms || [], 3).map((term) => `<li>Matched: ${escapeHtml(ownerText(term))}</li>`).join("")}
      </ul>
    </article>
  `;
}

function renderSimilarAwardsCard(scorecard) {
  const examples = firstItems(scorecard.similar_award_examples || [], 3);
  if (!examples.length) {
    return "";
  }
  const range = scorecard.similar_award_range || "Award range available from historical records";
  return `
    <article class="scorecard-item wide similar-awards-card">
      <span>Similar Past Awards</span>
      <strong>${escapeHtml(range)}</strong>
      <ul class="proof-list">
        ${examples.map((award) => {
    const value = award.award_value_label || (award.award_value ? formatMoney(award.award_value) : "value not listed");
    const descriptor = shortText(award.description || award.document_number || "Historical award", 120);
    const division = award.division ? ` / ${award.division}` : "";
    return `<li>${escapeHtml(value)}${escapeHtml(division)} - ${escapeHtml(ownerText(descriptor))}</li>`;
  }).join("")}
      </ul>
    </article>
  `;
}

function renderFalsePositiveCategoriesCard(scorecard) {
  const categories = firstItems(scorecard.false_positive_categories || [], 5);
  if (!categories.length) {
    return "";
  }
  return `
    <article class="scorecard-item wide false-positive-card">
      <span>Listings We Passed On</span>
      <strong>${number(scorecard.false_positives_skipped)} misleading matches skipped</strong>
      <ul class="proof-list">
        ${categories.map((category) => {
    const label = `${category.category || "Uncategorized"} / ${category.blocker || "weak evidence"}`;
    return `<li>${escapeHtml(ownerText(label))}: ${number(category.count)} skipped</li>`;
  }).join("")}
      </ul>
    </article>
  `;
}

function renderCapacityReviewCard(scorecard) {
  const examples = firstItems(scorecard.capacity_examples || [], 3);
  const reasons = firstItems(scorecard.capacity_downgrade_reasons || [], 3);
  if (!examples.length && !reasons.length) {
    return "";
  }
  const lines = reasons.length
    ? reasons.map((item) => `${ownerText(item.reason || "Needs a closer look")} (${number(item.count)})`)
    : examples.map((item) => `${item.document_number || "Listing"}: ${ownerText(firstItems(item.capacity_warnings || item.reasons || [], 1)[0] || item.recommended_action || "needs a closer look")}`);
  return `
    <article class="scorecard-item wide capacity-card">
      <span>Team Capacity</span>
      <strong>${number(scorecard.capacity_downgrades)} listings held for a closer look</strong>
      <ul class="proof-list">
        ${firstItems(lines, 4).map((line) => `<li>${escapeHtml(shortText(line, 180))}</li>`).join("")}
      </ul>
    </article>
  `;
}

function renderBidFitnessTrace(item, requirements) {
  if (!item) {
    return `
      <article class="bid-fitness-trace empty-trace">
        <div class="trace-header">
          <div>
            <p class="eyebrow">Why This Decision</p>
            <h4>No listing selected</h4>
            <span>Find matches or select a row to see why it was recommended or passed over.</span>
          </div>
          <span class="count-pill">Waiting</span>
        </div>
      </article>
    `;
  }

  const trace = normalizedBidFitnessTrace(item, requirements);
  const label = decisionLabel(item.label);
  const subtitle = label === "Skip"
    ? "Why we passed on this listing"
    : "Why this listing is shown";

  return `
    <article class="bid-fitness-trace">
      <div class="trace-header">
        <div>
          <p class="eyebrow">Why This Decision</p>
          <h4>${escapeHtml(getTitle(item))}</h4>
          <span>${escapeHtml(subtitle)}</span>
        </div>
        <span class="count-pill">${trace.hasBackendTrace ? "Checked details" : "Basic evidence"}</span>
      </div>
      <div class="trace-grid">
        ${renderTraceBucket("Deal Breakers", trace.hardBlockers, "blocker", "No deal-breaker reported.")}
        ${renderTraceBucket("Checks Used", trace.rulesTriggered, "rule", "No specific check returned.")}
        ${renderTraceBucket("Things To Confirm", trace.softWarnings, "warning", "No warning reported.")}
        ${renderTraceBucket("Why It Looks Good", trace.positiveSignals, "positive", "No positive signal reported.")}
        ${renderTraceBucket("Documents / Requirements", trace.requirementSignals, "requirement", "No requirement signal reported.")}
        ${renderTraceBucket("Team Capacity", trace.capacityGates, "capacity", "No capacity issue reported.")}
        ${renderTraceBucket("Similar Past Awards", trace.historicalAnalogs, "history", "No similar past award returned.")}
        ${renderTraceBucket("Summary Labels", trace.scorecardLabels, "scorecard", "No summary label returned.", 10)}
      </div>
      <div class="trace-rationale">
        <span>Bottom Line</span>
        <p>${escapeHtml(ownerText(trace.finalRationale))}</p>
      </div>
    </article>
  `;
}

function renderTraceBucket(label, items, modifier, emptyText, limit = 6) {
  const safeItems = firstItems(uniqueTextItems(textItems(items)), limit);
  return `
    <section class="trace-bucket trace-${escapeHtml(modifier)}">
      <h5>${escapeHtml(label)}</h5>
      ${safeItems.length
    ? `<ul>${safeItems.map((item) => `<li>${escapeHtml(ownerText(item))}</li>`).join("")}</ul>`
    : `<p>${escapeHtml(emptyText)}</p>`}
    </section>
  `;
}

function normalizedBidFitnessTrace(item, requirements) {
  const raw = rawBidFitnessTrace(item);
  const hasBackendTrace = Object.keys(raw).some((key) => hasDisplayValue(raw[key]));
  const label = decisionLabel(item && item.label);
  const supporting = supportingLabels(item);
  const rawHardBlockers = textItems(raw.hard_blockers);
  const hardBlockers = uniqueTextItems(rawHardBlockers.length ? rawHardBlockers : [
    ...textItems(item && item.hard_blockers),
    ...(label === "Skip" ? textItems(item && item.rejection_reasons) : []),
    ...textItems(item && item.missing_requirements).map((requirement) => `Missing requirement: ${requirement}`)
  ]);
  const rulesFromBackend = uniqueTextItems([
    ...textItems(raw.rules_triggered),
    ...textItems(item && item.rules_triggered),
    ...textItems(item && item.rejection_rules),
    ...textItems(item && item.rule_hits)
  ]);
  const rulesTriggered = rulesFromBackend.length
    ? rulesFromBackend
    : label === "Skip"
      ? firstItems(hardBlockers, 3).map((blocker) => `Derived blocker rule: ${blocker}`)
      : [];
  const rawSoftWarnings = textItems(raw.soft_warnings);
  const softWarnings = uniqueTextItems(rawSoftWarnings.length ? rawSoftWarnings : [
    ...textItems(item && item.soft_warnings),
    ...textItems(item && item.risks),
    ...capacityWarningItems(item)
  ]);
  const rawPositiveSignals = textItems(raw.positive_signals);
  const positiveSignals = uniqueTextItems(rawPositiveSignals.length ? rawPositiveSignals : [
    ...textItems(item && item.positive_signals),
    ...(label !== "Skip" ? textItems(item && item.reasons) : []),
    ...firstItems(item && item.matched_terms, 4).map((term) => `Matched term: ${term}`)
  ]);
  const requirementSignals = uniqueTextItems([
    ...textItems(raw.requirement_signals),
    ...textItems(item && item.requirement_signals),
    ...requirementSignalItems(requirements),
    ...firstItems(item && item.matched_terms, 4).map((term) => `Matched term: ${term}`)
  ]);
  const rawCapacityGates = textItems(raw.capacity_gates);
  const capacityGates = uniqueTextItems(rawCapacityGates.length ? rawCapacityGates : [
    ...textItems(item && item.capacity_gates),
    ...capacityGateItems(item, requirements)
  ]);
  const rawHistoricalAnalogs = textItems(raw.historical_analogs);
  const historicalAnalogs = uniqueTextItems(rawHistoricalAnalogs.length ? rawHistoricalAnalogs : [
    ...textItems(item && item.historical_analogs),
    ...historicalAnalogItems(item)
  ]);
  const rawScorecardLabels = scorecardLabelItems(raw.scorecard_labels);
  const scorecardLabels = uniqueTextItems(rawScorecardLabels.length ? rawScorecardLabels : [
    ...scorecardLabelItems(item && item.scorecard_labels),
    ...fallbackScorecardLabels(supporting)
  ]);

  return {
    hasBackendTrace,
    hardBlockers,
    rulesTriggered,
    softWarnings,
    positiveSignals,
    requirementSignals,
    capacityGates,
    historicalAnalogs,
    scorecardLabels,
    finalRationale: singleText(raw.final_rationale)
      || singleText(item && item.final_rationale)
      || finalReason(item, requirements)
  };
}

function rawBidFitnessTrace(item) {
  const trace = item && item.bid_fitness_trace;
  return isPlainObject(trace) ? trace : {};
}

function requirementSignalItems(requirements) {
  if (!requirements || typeof requirements !== "object") {
    return [];
  }
  const fields = [
    ["services", "Services"],
    ["certifications", "Certifications"],
    ["documents", "Documents"],
    ["facility_signals", "Facility signals"],
    ["procurement_type", "Buying process"]
  ];
  return fields.flatMap(([key, label]) => {
    const values = textItems(requirements[key]);
    return values.length ? [`${label}: ${values.join(", ")}`] : [];
  });
}

function capacityGateItems(item, requirements) {
  const assessment = getCapacityAssessment(item);
  const items = [];
  if (assessment) {
    if (assessment.pursuit_load) {
      items.push(`Current bid load: ${assessment.pursuit_load}`);
    }
    if (assessment.response_capacity) {
      items.push(`Time to respond: ${assessment.response_capacity}`);
    }
    if (assessment.execution_capacity) {
      items.push(`Team capacity: ${assessment.execution_capacity}`);
    }
    if (assessment.recommended_action) {
      items.push(`Suggested next step: ${ownerText(assessment.recommended_action)}`);
    }
  }
  if (requirements) {
    items.push(...textItems(requirements.capacity_flags).map((flag) => `Capacity note: ${flag}`));
  }
  items.push(...capacityWarningItems(item));
  return items;
}

function historicalAnalogItems(item) {
  if (!item) {
    return [];
  }
  const history = formatHistory(item.historical, item.label);
  return history ? [history] : [];
}

function scorecardLabelItems(labels) {
  if (!hasDisplayValue(labels)) {
    return [];
  }
  if (isPlainObject(labels)) {
    return Object.entries(labels).map(([key, value]) => (
      `${titleCase(humanizeToken(key))}: ${formatTraceValue(value)}`
    ));
  }
  return textItems(labels);
}

function fallbackScorecardLabels(supporting) {
  return Object.entries(supporting || {})
    .filter(([, value]) => hasDisplayValue(value))
    .map(([key, value]) => `${titleCase(humanizeToken(key))}: ${formatTraceValue(value)}`);
}

function renderScorecardProofArtifacts(result, scorecard) {
  const proofSpecs = [
    ["Usability Proof", firstPresent([
      scorecard.usability,
      scorecard.usability_proof,
      result.usability_proof
    ])],
    ["Technical Depth Proof", firstPresent([
      scorecard.technical_depth,
      scorecard.technical_depth_proof,
      result.technical_depth_proof
    ])],
    ["Baseline", firstPresent([
      scorecard.baseline,
      scorecard.baselines,
      scorecard.baseline_metrics,
      result.baseline,
      result.baselines
    ])],
    ["Benchmark", firstPresent([
      scorecard.benchmark,
      scorecard.benchmarks,
      scorecard.benchmark_metrics,
      result.benchmark,
      result.benchmarks
    ])]
  ];
  const knownKeys = new Set([
    "false_positives_skipped",
    "similar_awards_grounded",
    "estimated_bid_hours_saved",
    "realistic_historical_opportunities",
    "profile",
    "evaluated_count",
    "actionable_count",
    "capacity_downgrades",
    "capacity_downgrade_reasons",
    "false_positive_examples",
    "false_positive_categories",
    "capacity_examples",
    "best_current_opportunity",
    "buyer_division_pattern",
    "similar_award_range",
    "similar_award_examples",
    "top_insight",
    "usability",
    "usability_proof",
    "technical_depth",
    "technical_depth_proof",
    "baseline",
    "baselines",
    "baseline_metrics",
    "benchmark",
    "benchmarks",
    "benchmark_metrics"
  ]);
  const explicitProof = proofSpecs
    .map(([label, value]) => renderScorecardProofArticle(label, value))
    .join("");
  const extraProof = Object.keys(scorecard)
    .filter((key) => !knownKeys.has(key) && hasDisplayValue(scorecard[key]))
    .slice(0, 3)
    .map((key) => renderScorecardProofArticle(titleCase(humanizeToken(key)), scorecard[key]))
    .join("");
  return explicitProof + extraProof;
}

function renderScorecardProofArticle(label, value) {
  const lines = firstItems(scorecardProofLines(value), 6);
  if (!lines.length) {
    return "";
  }
  const [summary, ...details] = lines;
  return `
    <article class="scorecard-item wide proof-artifact">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(summary)}</strong>
      ${details.length
    ? `<ul class="proof-list">${details.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
    : ""}
    </article>
  `;
}

function scorecardProofLines(value) {
  if (!hasDisplayValue(value)) {
    return [];
  }
  if (isPlainObject(value)) {
    return uniqueTextItems(Object.entries(value).map(([key, entry]) => (
      `${titleCase(humanizeToken(key))}: ${formatTraceValue(entry)}`
    )));
  }
  return uniqueTextItems(textItems(value));
}

function renderEvaluatedStream(items) {
  const container = $("evaluatedStream");
  container.className = items.length ? "table-list" : "table-list empty-list";
  if (!items.length) {
    container.innerHTML = "<p>No checked listings yet.</p>";
    return;
  }

  container.innerHTML = items.map((item) => {
    const solicitation = item.solicitation || {};
    return `
      <div class="stream-row">
        <strong>${escapeHtml(getCompactOpportunityTitle(item, 150))}</strong>
        <span class="label-pill ${labelClass(item.label)}">${escapeHtml(ownerDecisionLabel(item.label))}</span>
        <span>${escapeHtml(solicitation.submission_deadline || "No deadline")}</span>
      </div>
    `;
  }).join("");
}

function renderTimeline(items) {
  const container = $("timeline");
  if (!container) {
    return;
  }
  container.className = items.length ? "timeline" : "timeline empty-list";
  if (!items.length) {
    container.innerHTML = "<p>Pick a month to see deadline reminders and next steps.</p>";
    return;
  }

  container.innerHTML = items.map((item) => {
    const date = item.date || item.day || item.when || "Day";
    const title = item.title || item.event || item.type || "Timeline event";
    const body = item.description || item.message || item.detail || "";
    return `
      <div class="timeline-item">
        <div class="timeline-date">${escapeHtml(String(date))}</div>
        <div class="timeline-body">
          <strong>${escapeHtml(ownerText(String(title)))}</strong>
          <span>${escapeHtml(ownerText(String(body)))}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderPacket(packet, approved, packetExport = null) {
  const container = $("packetOutput");
  if (!container) {
    return;
  }
  if (!packet) {
    container.className = "packet-output empty-list";
    container.innerHTML = `<p>No ${approvalArtifactNoun()} returned.</p>`;
    container.hidden = false;
    return;
  }

  container.className = "packet-output";
  container.hidden = false;
  const contact = packet.buyer_contact || {};
  const ownerReady = Boolean(packet.owner_ready);
  const statusText = ownerReady
    ? `${approvalArtifactTitle()} are ready for owner review. Submission is not sent from this workspace.`
    : "Choose a listing first.";
  const checklist = firstItems(packet.checklist || [], 3).map(cleanDisplayText);
  const questions = firstItems(packet.clarification_questions || [], 2).map(cleanDisplayText);
  const contactLines = [contact.name, contact.email, contact.phone].filter(Boolean);
  const complianceSummary = packet.compliance_summary || {};
  const complianceDecision = packet.compliance_decision || {};
  const complianceOpenItems = firstItems(packet.compliance_open_items || [], 3).map(cleanDisplayText);
  const complianceText = complianceSummary.total
    ? complianceSummaryText(complianceSummary)
    : "No PDF compliance matrix was attached.";
  const pricingWorksheet = packet.pricing_worksheet || {};
  const pdfLineItems = Array.isArray(pricingWorksheet.pricing_line_items) ? pricingWorksheet.pricing_line_items : [];
  const lineItemRollup = pricingWorksheet.line_item_rollup && typeof pricingWorksheet.line_item_rollup === "object" ? pricingWorksheet.line_item_rollup : {};
  const pricingLines = pricingWorksheet.target_bid
    ? [
        `Target: ${formatMoney(pricingWorksheet.target_bid)}`,
        `Range: ${formatMoney(pricingWorksheet.low_bid || 0)}-${formatMoney(pricingWorksheet.high_bid || 0)}`,
        `Confidence: ${pricingWorksheet.confidence || "Unknown"}`,
        `Status: ${humanizeToken(pricingWorksheet.status || "draft")}`,
        pdfLineItems.length ? `PDF quantities: ${number(pdfLineItems.length)} line item${pdfLineItems.length === 1 ? "" : "s"}` : "",
        lineItemRollup.target_bid ? `Quantity rollup: ${formatMoney(lineItemRollup.target_bid)} / ${percent(lineItemRollup.coverage || 0)} coverage` : "",
        lineItemRollup.rate_card_source ? `Rate source: ${humanizeToken(lineItemRollup.rate_card_source)}` : ""
      ]
      .filter(Boolean)
    : [];
  const pricingBlockers = firstItems(pricingWorksheet.blockers || [], 2).map(cleanDisplayText);
  const submissionManifest = Array.isArray(packet.submission_manifest) ? packet.submission_manifest : [];
  const manifestSummary = packet.submission_manifest_summary || {};
  const openManifestItems = firstItems(
    submissionManifest.filter((item) => item && item.status !== "ready"),
    4
  ).map((item) => `${humanizeToken(item.status || "review")}: ${cleanDisplayText(item.label || item.item_type || "Submission item")}`);
  const manifestLines = openManifestItems.length
    ? openManifestItems
    : firstItems(submissionManifest, 4).map((item) => `${humanizeToken(item.status || "ready")}: ${cleanDisplayText(item.label || item.item_type || "Submission item")}`);
  const agentSummary = packet.agent_summary || {};
  const exportInfo = packetExport && typeof packetExport === "object" ? packetExport : {};
  const agentAuditLines = agentSummary.evidence_fact_count !== undefined
    ? [
        `Decision: ${ownerDecisionLabel(complianceDecision.label || agentSummary.compliance_decision_label || "")}`,
        `State: ${agentStateLabel(agentSummary.bid_state)}`,
        `Facts: ${number(agentSummary.evidence_fact_count || 0)}`,
        `Actions: ${number(agentSummary.action_count || 0)}`,
        `Open gates: ${number(agentSummary.gate_count || 0)}`
      ]
    : [];
  container.innerHTML = `
    <div class="packet-result-title">
      <span>Prepared ${escapeHtml(approvalArtifactTitle())}</span>
      <strong>${escapeHtml(ownerReady ? "Ready" : "Review first")}</strong>
    </div>
    <div class="packet-grid">
      <div class="packet-card packet-primary">
        <strong>${escapeHtml(shortText(cleanDisplayText(packet.title || `Prepared ${approvalArtifactNoun()}`), 120))}</strong>
        <span>${escapeHtml(shortText(cleanDisplayText(packet.summary || `${approvalArtifactTitle()} prepared from the match details.`), 240))}</span>
      </div>
      <div class="packet-card packet-status-card">
        <strong>Status</strong>
        <span>${escapeHtml(statusText)}</span>
        ${exportInfo.download_url ? `<a class="packet-export-link" href="${escapeHtml(exportInfo.download_url)}" download="${escapeHtml(exportInfo.filename || "packet-export.md")}">Download Markdown</a>` : ""}
      </div>
      <div class="packet-card packet-compliance-card">
        <strong>PDF Compliance</strong>
        <span>${escapeHtml(complianceText)}</span>
        ${complianceOpenItems.length ? renderList(complianceOpenItems) : ""}
      </div>
      ${pricingLines.length ? `
        <div class="packet-card packet-pricing-card">
          <strong>Pricing Worksheet</strong>
          <span>${escapeHtml(pricingWorksheet.can_use_for_owner_packet ? "Deterministic pricing range ready for owner review." : "Pricing needs review before final use.")}</span>
          ${renderList([...pricingLines, ...pricingBlockers])}
        </div>
      ` : ""}
      ${agentAuditLines.length ? `
        <div class="packet-card packet-agent-card">
          <strong>Agent Audit</strong>
          <span>${escapeHtml(cleanDisplayText(agentSummary.next_action || "Deterministic runtime complete."))}</span>
          ${renderList(agentAuditLines)}
        </div>
      ` : ""}
      ${submissionManifest.length ? `
        <div class="packet-card packet-manifest-card">
          <strong>Submission Readiness</strong>
          <span>${escapeHtml(manifestSummary.required_open ? `${number(manifestSummary.required_open)} required item${manifestSummary.required_open === 1 ? "" : "s"} still open before submission.` : "Required submission items are ready for human review.")}</span>
          ${renderList(manifestLines)}
        </div>
      ` : ""}
      <div class="packet-card">
        <strong>Next Steps</strong>
        ${renderList(checklist)}
      </div>
      ${questions.length ? `
        <div class="packet-card">
          <strong>Buyer Questions</strong>
          ${renderList(questions)}
        </div>
      ` : ""}
      <div class="packet-card">
        <strong>Buyer Contact</strong>
        ${renderList(contactLines)}
      </div>
    </div>
  `;
}

function setView(view) {
  state.activeView = view;
  $("ownerTab").classList.toggle("active", view === "owner");
  $("evidenceTab").classList.toggle("active", view === "evidence");
  $("ownerView").classList.toggle("active", view === "owner");
  $("evidenceView").classList.toggle("active", view === "evidence");
}

function setBusy(isBusy, message = "") {
  const canRun = hasActiveProfile();
  const scanButton = $("scanButton");
  const approveButton = $("approveButton");
  scanButton.disabled = isBusy || !canRun;
  scanButton.textContent = isBusy ? "Running..." : "Run Bid Agent";
  $("monthSelector").disabled = isBusy || !canRun;
  approveButton.disabled = isBusy || !canApproveCurrent();
  if (isBusy && message.toLowerCase().includes("bid notes")) {
    approveButton.textContent = "Preparing...";
  } else {
    approveButton.innerHTML = "<span>Prepare Bid Notes</span>";
  }
  if (isBusy && message) {
    showToast(message);
  }
}

function canApproveCurrent() {
  const selected = findSelectedOpportunity();
  const analysis = selected ? selectedDocumentAnalysis(selected) : null;
  const summary = analysis && analysis.compliance_summary;
  return Boolean(
    selected
      && !["Skip", "Pass", "Blocked"].includes(effectiveDecisionLabel(selected))
      && analysis
      && summary
      && summary.ready_to_prepare
      && analysis.bid_state === "owner_packet_ready"
      && !state.documentAcquireBusy
      && !state.documentUploadBusy
      && !state.pricingApproveBusy
  );
}

async function apiGet(path) {
  const response = await fetch(path);
  return parseResponse(response);
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseResponse(response);
}

async function apiPostStream(path, payload, onEvent) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    return parseResponse(response);
  }
  if (!response.body) {
    return apiPost("/api/scan", payload);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      const event = parseStreamEvent(line);
      if (!event) {
        continue;
      }
      if (event.event === "error") {
        throw new Error(event.error || "Streaming scan failed.");
      }
      if (event.event === "done") {
        finalResult = event.result;
      } else {
        onEvent(event);
      }
    }
  }

  const tail = decoder.decode();
  if (tail) {
    buffer += tail;
  }
  const finalEvent = parseStreamEvent(buffer);
  if (finalEvent) {
    if (finalEvent.event === "error") {
      throw new Error(finalEvent.error || "Streaming scan failed.");
    }
    if (finalEvent.event === "done") {
      finalResult = finalEvent.result;
    } else {
      onEvent(finalEvent);
    }
  }

  if (!finalResult) {
    throw new Error("Scan finished without a final result.");
  }
  return finalResult;
}

function parseStreamEvent(line) {
  const trimmed = String(line || "").trim();
  if (!trimmed) {
    return null;
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

async function parseResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function renderTags(container, items) {
  container.innerHTML = (items || [])
    .map((item) => `<span class="tag">${escapeHtml(String(item))}</span>`)
    .join("");
}

function renderEvidenceTags(container, items) {
  const safeItems = firstItems(items || [], 6);
  container.innerHTML = safeItems.length
    ? safeItems.map((item) => `<span class="tag">${escapeHtml(String(item))}</span>`).join("")
    : "<span class=\"tag muted-tag\">Not listed</span>";
}

function renderList(items) {
  if (!items.length) {
    return "<p>None listed.</p>";
  }
  return `<ul>${items.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>`;
}

function renderOrderedList(items) {
  if (!items.length) {
    return "<p>None listed.</p>";
  }
  return `<ol>${items.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ol>`;
}

function getOpportunityId(item) {
  return String((item.solicitation || {}).document_number || "");
}

function getTitle(item) {
  const solicitation = item.solicitation || {};
  return getPlainOpportunitySummary(item)
    || solicitation.description
    || solicitation.document_number
    || "Untitled city listing";
}

function getCompactOpportunityTitle(item, maxLength = 140) {
  const solicitation = (item && item.solicitation) || {};
  const requirements = getStructuredRequirements(item);
  const scopeTerms = firstItems(
    ((requirements && requirements.services) || item.matched_terms || [])
      .map((term) => String(term || "").trim())
      .filter((term) => term && term.length <= 44),
    3
  );
  if (scopeTerms.length) {
    const scope = `${scopeTerms.join(", ")}${solicitation.division ? ` / ${solicitation.division}` : ""}`;
    return shortText(scope, maxLength);
  }
  const title = String(getTitle(item) || "").trim();
  const firstClause = title.split(";")[0] || title;
  const cleaned = firstClause
    .replace(/^this is\s+/i, "")
    .replace(/\s+/g, " ")
    .replace(/\.$/, "")
    .trim();
  return shortText(cleaned || title, maxLength);
}

function shortText(value, maxLength) {
  const text = String(value || "").trim();
  if (text.length <= maxLength) {
    return text;
  }
  const clipped = text.slice(0, maxLength - 1);
  const lastSpace = clipped.lastIndexOf(" ");
  return `${clipped.slice(0, lastSpace > 60 ? lastSpace : clipped.length).trim()}...`;
}

function getPlainOpportunitySummary(item) {
  if (!item) {
    return "";
  }
  const brief = getOpportunityBrief(item);
  const briefSummary = String((brief && brief.owner_summary) || "").trim();
  if (briefSummary) {
    return briefSummary;
  }
  const requirements = getStructuredRequirements(item);
  const solicitation = item.solicitation || {};
  const officialDescription = String(solicitation.description || "").trim();
  const extractedSummary = String((requirements && requirements.summary) || "").trim();
  const extractedKey = extractedSummary.toLowerCase();
  const officialKey = officialDescription.toLowerCase();
  if (extractedSummary && (!officialKey || (extractedKey !== officialKey && !extractedKey.includes(officialKey)))) {
    return extractedSummary;
  }

  const services = firstItems((requirements && requirements.services) || item.matched_terms || [], 3);
  const division = String(solicitation.division || "").trim();
  if (services.length) {
    return `This is ${humanList(services)} work${division ? ` for ${division}` : ""}.`;
  }
  const category = String(solicitation.category || "").trim();
  if (category && division) {
    return `${category} city listing from ${division}.`;
  }
  if (category) {
    return `${category} city listing.`;
  }
  return "";
}

function getOpportunityBrief(item) {
  if (!item) {
    return null;
  }
  const brief = item.opportunity_brief;
  return brief && typeof brief === "object" ? brief : null;
}

function getMarketFit(item) {
  if (!item || !item.market_fit || typeof item.market_fit !== "object") {
    return null;
  }
  return item.market_fit;
}

function getBidRecommendation(item) {
  if (!item || !item.bid_recommendation || typeof item.bid_recommendation !== "object") {
    return null;
  }
  const recommendation = item.bid_recommendation;
  return recommendation.recommended_bid ? recommendation : null;
}

function getPricingBreakdown(item) {
  if (!item || !item.pricing_breakdown || typeof item.pricing_breakdown !== "object") {
    return null;
  }
  const pricing = item.pricing_breakdown;
  return pricing.recommended_bid ? pricing : null;
}

function getPricingWorksheet(item) {
  if (!item || !item.pricing_worksheet || typeof item.pricing_worksheet !== "object") {
    return null;
  }
  const worksheet = item.pricing_worksheet;
  return worksheet.target_bid ? worksheet : null;
}

function bidRecommendationLabel(item) {
  const worksheet = getPricingWorksheet(item);
  if (worksheet) {
    return `Bid ${formatMoney(worksheet.target_bid)}`;
  }
  const pricing = getPricingBreakdown(item);
  if (pricing) {
    return `Bid ${formatMoney(pricing.recommended_bid)}`;
  }
  const recommendation = getBidRecommendation(item);
  if (!recommendation) {
    return "";
  }
  return `Bid ${formatMoney(recommendation.recommended_bid)}`;
}

function bidRecommendationLanguage(item) {
  const worksheet = getPricingWorksheet(item);
  const pricing = getPricingBreakdown(item);
  const recommendation = getBidRecommendation(item);
  if (!item) {
    return "Bid guidance appears after a city listing is checked.";
  }
  if (worksheet) {
    const blockers = firstItems(worksheet.blockers || [], 2);
    const missingInputs = firstItems((worksheet.missing_inputs || []).map((item) => item.reason || item.input_type).filter(Boolean), 2);
    if (String(worksheet.status || "").startsWith("blocked") || blockers.length || missingInputs.length) {
      return `Pricing worksheet is blocked: ${humanList([...blockers, ...missingInputs])}.`;
    }
    const assumptions = firstItems(worksheet.assumptions || [], 2);
    const risks = firstItems(worksheet.risks || [], 2);
    const lineItems = Array.isArray(worksheet.pricing_line_items) ? worksheet.pricing_line_items : [];
    const rollup = worksheet.line_item_rollup && typeof worksheet.line_item_rollup === "object" ? worksheet.line_item_rollup : {};
    const quantityText = lineItems.length ? ` PDF quantity basis: ${number(lineItems.length)} cited line item${lineItems.length === 1 ? "" : "s"}. ` : "";
    const rateSource = rollup.rate_card_source ? ` using ${humanizeToken(rollup.rate_card_source).toLowerCase()} rates` : "";
    const rollupText = rollup.target_bid ? ` Quantity rollup targets ${formatMoney(rollup.target_bid)} from ${formatMoney(rollup.direct_cost || 0)} direct cost${rateSource}. ` : "";
    return (
      `Pricing worksheet targets ${formatMoney(worksheet.target_bid)} with range ` +
      `${formatMoney(worksheet.low_bid)} to ${formatMoney(worksheet.high_bid)} and ${worksheet.confidence || "Unknown"} confidence. ` +
      quantityText +
      rollupText +
      `${assumptions.length ? `Assumptions: ${humanList(assumptions)}. ` : ""}` +
      `${risks.length ? `Risks: ${humanList(risks)}.` : ""}`
    ).replace(/\s+/g, " ").trim();
  }
  if (pricing) {
    const drivers = firstItems(pricing.drivers || [], 3);
    const driverText = drivers.length ? ` Drivers: ${humanList(drivers)}.` : "";
    return (
      `Pricing engine recommends ${formatMoney(pricing.recommended_bid)}. ` +
      `It starts from ${formatMoney(pricing.market_reference)} market value, estimates ` +
      `${formatMoney(pricing.direct_cost)} direct cost, ${formatMoney(pricing.contingency)} contingency, ` +
      `${formatMoney(pricing.overhead)} overhead, and targets ${Math.round(Number(pricing.margin_rate || 0) * 100)}% margin. ` +
      `Expected profit ${formatMoney(pricing.expected_profit)} at ${Math.round(Number(pricing.win_probability || 0) * 100)}% win probability.${driverText}`
    ).replace(/\s+/g, " ").trim();
  }
  if (!recommendation) {
    return "Not enough historical award value evidence to suggest a bid amount.";
  }
  const amount = formatMoney(recommendation.recommended_bid);
  const range = recommendation.low_bid && recommendation.high_bid && recommendation.low_bid !== recommendation.high_bid
    ? ` Suggested range ${formatMoney(recommendation.low_bid)} to ${formatMoney(recommendation.high_bid)}.`
    : "";
  const evidence = firstItems(recommendation.evidence || [], 1)[0] || "";
  return `Bid around ${amount}. ${range} ${evidence}`.replace(/\s+/g, " ").trim();
}

function simulationLanguage(item) {
  const simulation = item && item.simulation_summary;
  if (!simulation || !simulation.iterations) {
    return "Revenue scenarios appear after the value model scores this listing.";
  }
  const range = `${formatMoney(simulation.likely_low)} to ${formatMoney(simulation.likely_high)}`;
  const downside = simulation.downside_case ? ` Downside ${formatMoney(simulation.downside_case)}.` : "";
  const driver = firstItems(simulation.drivers || [], 1)[0] || "";
  return `Likely revenue range ${range} (${simulation.confidence || "directional"} confidence).${downside} ${driver}`.replace(/\s+/g, " ").trim();
}

function portfolioLanguage(item) {
  const decision = item && item.portfolio_decision;
  if (!decision || !decision.decision) {
    return "Portfolio optimizer runs after revenue scoring and capacity checks.";
  }
  const value = decision.expected_value ? ` Expected value ${formatMoney(decision.expected_value)}.` : "";
  const effort = decision.estimator_hours ? ` Estimator effort ${number(decision.estimator_hours)} hours.` : "";
  const reason = firstItems(decision.reasons || [], 1)[0] || "";
  return `${decision.decision}.${value}${effort} ${reason}`.replace(/\s+/g, " ").trim();
}

function portfolioEngineLabel(engine) {
  if (engine === "greedy_capacity_optimizer" || engine === "greedy_fallback") {
    return "Capacity planner";
  }
  return titleCase(humanizeToken(engine || "portfolio optimizer"));
}

function portfolioModeDetail(metrics) {
  const mode = metrics && metrics.portfolio_mode;
  if (mode === "greedy_capacity_optimizer") {
    return "capacity and estimator load checked";
  }
  return "capacity planning ready";
}

function marketFitLabel(market) {
  if (!market) {
    return "Market not scored";
  }
  const confidence = market.confidence || "Market";
  const score = Number(market.score || 0);
  return `${confidence} market / ${Math.round(score * 100)}%`;
}

function marketFitLanguage(item) {
  const market = getMarketFit(item);
  if (!market) {
    return "Local award-history market score is pending.";
  }
  const evidence = firstItems(market.evidence || [], 2);
  if (evidence.length) {
    return evidence.join(" ");
  }
  return market.summary || marketFitLabel(market);
}

function briefSourceLabel(brief) {
  if (!brief || !brief.source) {
    return "Listing brief";
  }
  if (brief.source === "local_nim") {
    return "Detailed listing brief";
  }
  if (brief.source === "deterministic_fallback") {
    return "Basic listing brief";
  }
  return `${titleCase(humanizeToken(brief.source))} brief`;
}

function getSourceLinks(item) {
  const solicitation = (item && item.solicitation) || {};
  return solicitation.source_links && typeof solicitation.source_links === "object"
    ? solicitation.source_links
    : null;
}

function renderSourceActions(source) {
  if (!source) {
    return "";
  }
  const documentNumber = source.document_number || "";
  const docLabel = documentNumber ? `Listing ${documentNumber}` : "Toronto listing";
  const note = source.is_sample_record
    ? "Sample fallback record"
    : source.verification_note || "Official Toronto listing";
  return `
    <div class="source-actions">
      <span class="source-doc">${escapeHtml(docLabel)}</span>
      <span class="source-note">${escapeHtml(note)}</span>
    </div>
  `;
}

function renderOpportunityBrief(brief) {
  if (!brief) {
    return "";
  }
  const summary = String(brief.owner_summary || "").trim();
  const fitReason = String(brief.fit_reason || "").trim();
  const documents = firstItems(brief.required_documents || [], 3);
  const blockers = firstItems(brief.blockers || brief.missing_items || [], 2);
  const nextSteps = firstItems(brief.next_steps || [], 2);
  const source = briefSourceLabel(brief);
  const body = summary || fitReason || nextSteps[0] || "";
  if (!body && !documents.length && !blockers.length) {
    return "";
  }
  return `
    <div class="brief-panel ${brief.source === "local_nim" ? "brief-nim" : "brief-fallback"}">
      <div class="brief-heading">
        <strong>${escapeHtml(source)}</strong>
        ${brief.source === "local_nim" ? "<span>Ready</span>" : "<span>Basic</span>"}
      </div>
      ${body ? `<p>${escapeHtml(body)}</p>` : ""}
      ${documents.length ? `<div class="brief-row"><span>Docs</span><em>${escapeHtml(documents.join(", "))}</em></div>` : ""}
      ${blockers.length ? `<div class="brief-row warning"><span>Check</span><em>${escapeHtml(ownerText(blockers.join(", ")))}</em></div>` : ""}
      ${nextSteps.length ? `<div class="brief-row"><span>Next</span><em>${escapeHtml(nextSteps[0])}</em></div>` : ""}
    </div>
  `;
}

function briefReasonItems(brief) {
  if (!brief || typeof brief !== "object") {
    return [];
  }
  return uniqueTextItems([
    brief.fit_reason
  ]);
}

function formatHistory(history, label) {
  if (!history) {
    return "";
  }
  if (!history.similar_count) {
    return history.accessibility ? `History: ${history.accessibility}` : "";
  }
  const median = history.award_median ? formatMoney(history.award_median) : "unknown median";
  if (decisionLabel(label) === "Pursue" && String(history.accessibility || "").includes("partner")) {
    return `History: ${history.similar_count} similar awards, median ${median}; verify final scope before bidding`;
  }
  return `History: ${history.similar_count} similar awards, median ${median}, ${history.accessibility || "comparison available"}`;
}

function labelClass(label) {
  const normalized = String(decisionLabel(label) || "").toLowerCase().replace(/\s+/g, "-");
  return `label-${normalized}`;
}

function ownerDecisionLabel(label) {
  const labels = {
    Pursue: "Recommended Bid",
    Review: "Check First",
    Monitor: "Keep Watching",
    Skip: "Pass",
    Pass: "Pass",
    Blocked: "Blocked"
  };
  return labels[decisionLabel(label)] || "Keep Watching";
}

function decisionLabel(label) {
  const normalized = String(label || "").trim().toLowerCase();
  const replacements = {
    "bid this": "Pursue",
    urgent: "Pursue",
    "get partner": "Review",
    watchlist: "Monitor",
    monitor: "Monitor",
    pursue: "Pursue",
    review: "Review",
    skip: "Skip",
    pass: "Pass",
    blocked: "Blocked"
  };
  return replacements[normalized] || (label ? titleCase(label) : "Monitor");
}

function complianceDecisionForOpportunity(item = null) {
  const analysis = selectedDocumentAnalysis(item);
  const decision = analysis && analysis.compliance_decision;
  return decision && typeof decision === "object" ? decision : null;
}

function effectiveDecisionLabel(item) {
  const decision = complianceDecisionForOpportunity(item);
  return decision ? decisionLabel(decision.label) : decisionLabel(item && item.label);
}

function effectiveOwnerDecisionLabel(item) {
  const decision = complianceDecisionForOpportunity(item);
  return ownerDecisionLabel(decision ? decision.label : item && item.label);
}

function complianceDecisionReason(decision) {
  if (!decision) {
    return "";
  }
  return cleanDisplayText(decision.reason || "PDF compliance changed the bid decision.");
}

function complianceDecisionNextAction(decision) {
  if (!decision) {
    return "";
  }
  return cleanDisplayText(decision.next_action || decision.reason || "Resolve PDF compliance decision.");
}

function approvalArtifactNoun() {
  return "bid notes";
}

function approvalArtifactTitle() {
  return "Bid Notes";
}

function ownerText(value) {
  return String(value || "")
    .replace(/\bPursue Now\b/g, "Worth reviewing today")
    .replace(/\bPursue After Review\b/g, "Check first, then decide")
    .replace(/\bReview risks\b/gi, "Check risks")
    .replace(/\bReview the\b/gi, "Check the")
    .replace(/\bReview whether\b/gi, "Check whether")
    .replace(/\bReview all\b/gi, "Check all")
    .replace(/\bPursue\b/g, "Recommended Bid")
    .replace(/\bReview\b/g, "Check First")
    .replace(/\bMonitor\b/g, "Keep Watching")
    .replace(/\bSkip\b/g, "Pass")
    .replace(/\bsolicitations\b/gi, "city listings")
    .replace(/\bsolicitation\b/gi, "city listing")
    .replace(/\bsource package\b/gi, "city listing")
    .replace(/\bsource file\b/gi, "city listing")
    .replace(/\bsources\b/gi, "city listings")
    .replace(/\bsource\b/gi, "city listing")
    .replace(/\bapproval packet\b/gi, approvalArtifactNoun())
    .replace(/\bowner-ready packet\b/gi, `ready-to-use ${approvalArtifactNoun()}`)
    .replace(/\bpacket\b/gi, approvalArtifactNoun())
    .replace(/\bready-to-use bid notes blocked\b/gi, `${approvalArtifactTitle()} need the local bid brief`)
    .replace(/\bmodel call\(s\)\b/gi, "deep check(s)")
    .replace(/\bmodel calls\b/gi, "deep checks")
    .replace(/\bdeterministic\b/gi, "rule-based")
    .replace(/\bfalse-positive\b/gi, "misleading")
    .replace(/\bfalse positive\b/gi, "misleading")
    .replace(/\bblocker\b/gi, "concern")
    .replace(/\bblockers\b/gi, "concerns")
    .replace(/\bcapacity gate\b/gi, "capacity check")
    .replace(/\bowner review\b/gi, "a closer look")
    .replace(/\bprocurement\b/gi, "city buying")
    .replace(/\bopportunity\b/gi, "listing")
    .replace(/\bopportunities\b/gi, "listings");
}

function cleanDisplayText(value) {
  return ownerText(value)
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/\.;/g, ".")
    .replace(/;\./g, ".")
    .replace(/,;/g, ";")
    .replace(/([;:])(?=\S)/g, "$1 ")
    .replace(/,([^\s\d])/g, ", $1")
    .replace(/([.;:!?])\s+\1+/g, "$1")
    .trim();
}

function getPriorityMode() {
  return state.priorityMode;
}

function getSelectedProfileId() {
  const selected = document.querySelector('input[name="supportedProfile"]:checked');
  return selected ? selected.value : state.selectedProfileId;
}

function currentProfile() {
  return profileById(getSelectedProfileId()) || state.supportedProfiles[0] || LOADING_PROFILE;
}

function profileById(profileId) {
  return state.supportedProfiles.find((profile) => profile.profile_id === profileId) || null;
}

function profileWithSupportedEvidence(profile) {
  const supported = profileById(profile.profile_id);
  return supported ? { ...supported, ...profile } : profile;
}

function hasActiveProfile() {
  return Boolean(currentProfile().profile_id);
}

function selectedSnapshotMonth() {
  return SNAPSHOT_MONTHS_2026.find((month) => month.value === state.selectedSnapshotMonth)
    || SNAPSHOT_MONTHS_2026[SNAPSHOT_MONTHS_2026.length - 1];
}

function snapshotMonthForDate(value) {
  const yearMonth = String(value || "").slice(0, 7);
  if (!yearMonth) {
    return null;
  }
  return SNAPSHOT_MONTHS_2026.find((month) => month.value.slice(0, 7) === yearMonth) || null;
}

function syncMonthSelector() {
  const selector = $("monthSelector");
  if (selector) {
    selector.value = selectedSnapshotMonth().value;
  }
  updateSnapshotLabel();
}

function updateSnapshotLabel() {
  const label = $("snapshotEyebrow");
  if (label) {
    label.textContent = `${selectedSnapshotMonth().label} 2026`;
  }
}

function supportedProfilesFromHealth(health) {
  const profiles = Array.isArray(health && health.supported_profiles)
    ? health.supported_profiles.filter((profile) => profile && profile.profile_id)
    : [];
  const byId = new Map(profiles.map((profile) => [profile.profile_id, profile]));
  const orderedProfiles = PROFILE_ORDER
    .map((profileId) => byId.get(profileId))
    .filter(Boolean);
  const orderedIds = new Set(orderedProfiles.map((profile) => profile.profile_id));
  const extras = profiles.filter((profile) => profile.profile_id !== "building_mechanical" && !orderedIds.has(profile.profile_id));
  if (orderedProfiles.length) {
    return [...orderedProfiles, ...extras];
  }
  return extras;
}

function selectProfileId(candidateId) {
  if (profileById(candidateId)) {
    return candidateId;
  }
  if (profileById(DEFAULT_PROFILE_ID)) {
    return DEFAULT_PROFILE_ID;
  }
  return state.supportedProfiles[0] ? state.supportedProfiles[0].profile_id : "";
}

function profileLabel(profile) {
  return profile.label || profile.name || titleCase(humanizeToken(profile.profile_id)) || "Supported profile";
}

function compactProfileLabel(profile) {
  const labels = {
    road_civil_infrastructure: "Harbourfront Civil",
    parks_landscape: "Greenline Parks",
    professional_engineering_design: "CivicWorks Design"
  };
  return labels[profile.profile_id] || compactCompanyName(profile.name) || profileLabel(profile);
}

function compactCompanyName(name) {
  return String(name || "")
    .replace(/\s+(Ltd\.?|Limited|Inc\.?|Corporation|Corp\.?)$/i, "")
    .trim();
}

function profileCapacityText(profile) {
  const parts = [];
  if (profile.max_sites_per_day) {
    parts.push(`${profile.max_sites_per_day} city sites/day`);
  }
  if (profile.max_contract_value) {
    parts.push(`up to ${formatMoney(profile.max_contract_value)}`);
  }
  return parts.length ? parts.join(", ") : "Not listed";
}

function profileBondingText(profile) {
  if (profile.bonding_single_job_limit === 0) {
    return "Not needed for consulting profile";
  }
  if (profile.bonding_single_job_limit) {
    return `single job up to ${formatMoney(profile.bonding_single_job_limit)}`;
  }
  return "Not listed";
}

function profilePursuitsText(profile) {
  const active = profile.active_pursuit_count;
  const limit = profile.max_active_pursuits;
  if (active !== undefined && active !== null && limit !== undefined && limit !== null) {
    return `${active} active, limit ${limit}`;
  }
  return "Not listed";
}

function profileRateCardLabels(profile) {
  const rates = Array.isArray(profile.pricing_rate_card) ? profile.pricing_rate_card : [];
  const labels = rates
    .map((rate) => {
      const label = rate.label || rate.rate_id || "Rate";
      const unit = Array.isArray(rate.units) ? rate.units[0] : rate.unit;
      return rate.unit_direct_cost
        ? `${label}: ${formatMoney(rate.unit_direct_cost)}/${unit || "unit"}`
        : label;
    })
    .filter(Boolean);
  return labels.length ? firstItems(labels, 8) : ["No company rate card loaded"];
}

function uniqueProfileRateId(existingRates, label, unit) {
  const base = `company_${slugToken(label)}_${slugToken(unit)}`.replace(/_+/g, "_").replace(/^_|_$/g, "") || "company_rate";
  const used = new Set((existingRates || []).map((rate) => String(rate.rate_id || "")));
  if (!used.has(base)) {
    return base;
  }
  let index = 2;
  while (used.has(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}

function splitCommaList(value) {
  return String(value || "")
    .replace(/;/g, ",")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function slugToken(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function renderProfileEvidence(profile) {
  const evidence = $("profileEvidence");
  const divisions = $("profileDivisions");
  const goodFit = $("profileGoodFit");
  const badFit = $("profileBadFit");
  if (!evidence || !divisions || !goodFit || !badFit) {
    return;
  }

  evidence.innerHTML = `
    <div>
      <dt>Why This Type</dt>
      <dd>${escapeHtml(ownerText(profile.lane_basis || "Waiting for city listing evidence"))}</dd>
    </div>
    <div>
      <dt>2026 Matching Listings</dt>
      <dd>${profile.ytd_solicitation_hits === undefined ? "Not listed" : number(profile.ytd_solicitation_hits)}</dd>
    </div>
    <div>
      <dt>Strong Matches</dt>
      <dd>${profile.exclusive_best_fit_hits === undefined ? "Not listed" : number(profile.exclusive_best_fit_hits)}</dd>
    </div>
  `;
  renderEvidenceTags(divisions, profile.top_divisions || []);
  renderEvidenceTags(goodFit, profile.good_fit_examples || []);
  renderEvidenceTags(badFit, profile.bad_fit_examples || []);
}

function findSelectedOpportunity() {
  if (!state.scan || !state.selectedOpportunityId) {
    return null;
  }
  const groups = [
    state.scan.top_opportunities || [],
    state.scan.watchlist || [],
    state.scan.skipped || [],
    state.scan.all_evaluated || []
  ];
  return groups.flat().find((item) => getOpportunityId(item) === state.selectedOpportunityId) || null;
}

function selectedDocumentAnalysis(item = null) {
  const active = item || findSelectedOpportunity();
  const opportunityId = active ? getOpportunityId(active) : state.selectedOpportunityId;
  return opportunityId ? state.documentAnalyses[opportunityId] || null : null;
}

function complianceRowsForOpportunity(item = null) {
  const analysis = selectedDocumentAnalysis(item);
  return analysis && Array.isArray(analysis.compliance_matrix) ? analysis.compliance_matrix : [];
}

function complianceEvidenceLabel(evidence) {
  if (!evidence || typeof evidence !== "object") {
    return "";
  }
  const label = cleanDisplayText(evidence.label || evidence.evidence_type || evidence.type || "");
  if (!label) {
    return "";
  }
  return evidence.type === "vault_evidence" ? `${label} (vault)` : label;
}

function complianceRowState(row) {
  if (row && row.resolved) {
    return { key: "resolved", label: "Resolved" };
  }
  if (row && row.business_has_capability === false) {
    return { key: "capability_gap", label: "Capability Gap" };
  }
  if (row && row.evidence_needed && row.evidence_needed.length) {
    return { key: "evidence_needed", label: "Evidence Needed" };
  }
  return { key: "needs_review", label: "Needs Review" };
}

function complianceResolutionAction(row) {
  if (!row || row.resolved) {
    return null;
  }
  if (row.business_has_capability === false) {
    return { type: "capability_confirmed", label: "Confirm Capability" };
  }
  const actions = {
    site_visit: { type: "site_visit_attended", label: "Mark Attended" },
    addendum: { type: "addendum_acknowledged", label: "Acknowledge" },
    pricing_sheet: { type: "pricing_form_assigned", label: "Assign Form" },
    insurance: { type: "certificate_available", label: "Cert Available" },
    bonding: { type: "certificate_available", label: "Bond Ready" },
    license: { type: "certificate_available", label: "License Ready" },
    certification: { type: "certificate_available", label: "Cert Available" },
    safety: { type: "certificate_available", label: "Safety Ready" },
    experience: { type: "uploaded_evidence", label: "Refs Ready" },
    deadline: { type: "uploaded_evidence", label: "Calendar Done" },
    submission_instruction: { type: "uploaded_evidence", label: "Assign Owner" },
    form: { type: "uploaded_evidence", label: "Form Ready" }
  };
  return actions[row.category] || { type: "uploaded_evidence", label: "Mark Evidence" };
}

function evidenceTypeForCategory(category) {
  return {
    insurance: "insurance_certificate",
    bonding: "bonding_capacity",
    safety: "safety_document",
    license: "license",
    certification: "certification",
    experience: "reference_project",
    pricing_sheet: "pricing_form",
    form: "submission_form",
    site_visit: "site_visit_confirmation",
    addendum: "addendum_acknowledgement"
  }[category] || "uploaded_evidence";
}

function complianceSummaryText(summary) {
  if (!summary || !Number(summary.total || 0)) {
    return "PDF analyzed; no compliance gates found.";
  }
  const total = number(summary.total || 0);
  const resolved = number(summary.resolved || 0);
  const evidence = number(summary.evidence_needed || 0);
  const gaps = number(summary.capability_gap || 0);
  const hardStops = number(summary.hard_stops || 0);
  const reviewGates = number(summary.review_gates || 0);
  const review = number(summary.needs_review || 0);
  if (Number(summary.hard_stops || 0) || Number(summary.review_gates || 0)) {
    return `${resolved}/${total} resolved / ${hardStops} hard stop / ${reviewGates} review gate`;
  }
  if (Number(summary.unresolved || 0)) {
    return `${resolved}/${total} resolved / ${evidence} evidence / ${gaps} capability / ${review} review`;
  }
  return `${resolved}/${total} compliance gate(s) resolved`;
}

function agentStateLabel(value) {
  const labels = {
    metadata_intake: "City Record Intake",
    uploaded: "Uploaded",
    pdf_parsed: "PDF Parsed",
    requirements_extracted: "Requirements Extracted",
    evidence_gaps_open: "Evidence Gaps Open",
    requirements_resolved: "Requirements Resolved",
    owner_packet_ready: "Packet Ready"
  };
  return labels[value] || titleCase(humanizeToken(value || "Not Ready"));
}

function firstDecisionOpportunity() {
  if (!state.scan) {
    return null;
  }
  return (state.scan.top_opportunities || [])[0]
    || (state.scan.watchlist || [])[0]
    || (state.scan.skipped || [])[0]
    || (state.scan.all_evaluated || [])[0]
    || null;
}

function supportingLabels(item) {
  if (!item) {
    return {};
  }
  const evidence = item.evidence || item.decision_evidence || {};
  return {
    coreFit: item.core_fit || evidence.core_fit,
    eligibility: item.eligibility || evidence.eligibility,
    competition: item.competition || evidence.competition,
    pursuitEffort: item.pursuit_effort || evidence.pursuit_effort,
    deadlineRisk: item.deadline_risk || evidence.deadline_risk,
    strategicValue: item.strategic_value || evidence.strategic_value
  };
}

function getStructuredRequirements(item) {
  if (!item) {
    return null;
  }
  const requirements = item.requirements;
  return requirements && typeof requirements === "object" ? requirements : null;
}

function extractorSourceLabel(requirements) {
  if (!requirements || !requirements.source) {
    return "";
  }
  const sourceLabels = {
    local_nim: "local bid brief",
    deterministic_fallback: "basic rule check"
  };
  const source = sourceLabels[requirements.source] || humanizeToken(requirements.source);
  return `Brief from: ${source}`;
}

function requirementExtractionLanguage(item, requirements, fallbackTerms, solicitation) {
  if (!item) {
    return "Requirements will appear after a listing is checked.";
  }
  if (requirements) {
    const parts = [];
    const services = firstItems(requirements.services, 3);
    const certifications = firstItems(requirements.certifications, 2);
    const documents = firstItems(requirements.documents, 2);
    const facilitySignals = firstItems(requirements.facility_signals, 2);
    const procurementType = requirements.procurement_type;

    if (services.length) {
      parts.push(`Services: ${services.join(", ")}`);
    }
    if (certifications.length) {
      parts.push(`Certifications: ${certifications.join(", ")}`);
    }
    if (documents.length) {
      parts.push(`Documents: ${documents.join(", ")}`);
    }
    if (facilitySignals.length) {
      parts.push(`Facility signals: ${facilitySignals.join(", ")}`);
    }
    if (procurementType) {
      parts.push(`Buying process: ${procurementType}`);
    }
    if (parts.length) {
      return parts.join(". ") + ".";
    }
  }
  if (fallbackTerms.length) {
    return `Found scope signals: ${fallbackTerms.join(", ")}.`;
  }
  return `Used category and description to identify ${solicitation.category || "the type of work"}.`;
}

function awardLanguage(item) {
  const history = item && item.historical;
  if (!history) {
    return "Checks similar public awards when award history is available.";
  }
  if (!history.similar_count) {
    return history.accessibility || "No strong similar awards found in the comparison set.";
  }
  const median = history.award_median ? formatMoney(history.award_median) : "typical value not listed";
  return `${history.similar_count} similar awards found; typical award ${median}; ${history.accessibility || "scope looks comparable"}.`;
}

function riskLanguage(item, supporting, requirements) {
  if (!item) {
    return "Eligibility, deadline, and team capacity will be checked after the bid agent runs.";
  }
  const parts = [];
  const riskFlags = requirements ? firstItems(requirements.risk_flags, 3) : [];
  const capacityFlags = requirements ? firstItems(requirements.capacity_flags, 3) : [];
  const assessment = getCapacityAssessment(item);
  const assessmentWarnings = capacityWarningItems(item);
  const rejectionReasons = item ? firstItems(item.rejection_reasons, 3) : [];
  const deadlineRisk = (requirements && requirements.deadline_risk) || supporting.deadlineRisk;

  if (riskFlags.length) {
    parts.push(`Risks to check: ${riskFlags.join(", ")}`);
  }
  if (capacityFlags.length) {
    parts.push(`Capacity notes: ${capacityFlags.join(", ")}`);
  }
  if (rejectionReasons.length) {
    parts.push(`Reasons to pass: ${rejectionReasons.join(", ")}`);
  }
  if (assessment) {
    parts.push(
      `Current bid load: ${assessment.pursuit_load}`,
      `Time to respond: ${assessment.response_capacity}`,
      `Team capacity: ${assessment.execution_capacity}`,
      `Suggested next step: ${ownerText(assessment.recommended_action)}`
    );
  }
  if (assessmentWarnings.length) {
    parts.push(`Warning: ${assessmentWarnings[0]}`);
  }
  if (supporting.eligibility) {
    parts.push(`Eligibility: ${supporting.eligibility}`);
  }
  if (deadlineRisk) {
    parts.push(`Deadline risk: ${deadlineRisk}`);
  }
  if (supporting.pursuitEffort) {
    parts.push(`Bid effort: ${supporting.pursuitEffort}`);
  }
  if (parts.length) {
    return parts.join(". ") + ".";
  }
  const reasons = item.rejection_reasons || item.risks || [];
  return reasons.length ? firstItems(reasons, 2).join(" ") : "No obvious certification or capacity blocker surfaced.";
}

function nextActionSummary(item) {
  const trace = normalizedBidFitnessTrace(item, getStructuredRequirements(item));
  const decisionOverlay = complianceDecisionForOpportunity(item);
  return {
    recommendation: effectiveOwnerDecisionLabel(item),
    deadline: deadlinePressureText(item),
    task: decisionOverlay ? complianceDecisionNextAction(decisionOverlay) : ownerTaskText(item),
    fit: decisionOverlay ? complianceDecisionReason(decisionOverlay) : fitConfidenceText(item, trace)
  };
}

function deadlinePressureText(item) {
  const days = item && item.days_until_deadline;
  if (days === undefined || days === null || days === "") {
    return "Deadline unknown";
  }
  const numericDays = Number(days);
  if (!Number.isFinite(numericDays)) {
    return String(days);
  }
  if (numericDays < 0) {
    return "Closed";
  }
  if (numericDays === 0) {
    return "Due today";
  }
  if (numericDays === 1) {
    return "1 day left";
  }
  return `${numericDays} days left`;
}

function queueReason(item) {
  const requirements = getStructuredRequirements(item);
  const trace = normalizedBidFitnessTrace(item, requirements);
  const brief = getOpportunityBrief(item);
  const label = decisionLabel(item.label);
  const source = label === "Skip"
    ? blockerItems(item, trace, brief)
    : whyMatchedItems(item, trace, requirements, brief);
  return cleanDisplayText(ownerText(source[0] || finalReason(item, requirements)));
}

function ownerTaskText(item) {
  const requirements = getStructuredRequirements(item);
  const brief = getOpportunityBrief(item);
  const trace = normalizedBidFitnessTrace(item, requirements);
  const label = decisionLabel(item.label);
  const blockers = blockerItems(item, trace, brief);
  const warnings = capacityWarningItems(item);
  const assessment = getCapacityAssessment(item);
  const days = item.days_until_deadline;

  if (label === "Skip") {
    return blockers.length ? `Pass for now: ${shortText(ownerText(blockers[0]), 96)}` : "Do not spend bid time on this listing";
  }
  if (warnings.length || (assessment && assessment.recommended_action === "Pursue After Review")) {
    return "Check team capacity before deciding";
  }
  if (Number(days) >= 0 && Number(days) <= 2) {
    return "Confirm today whether you can respond in time";
  }
  if (requirements && requirements.next_action) {
    return shortText(ownerText(requirements.next_action), 110);
  }
  const nextSteps = textItems(brief && brief.next_steps);
  if (nextSteps.length) {
    return shortText(ownerText(nextSteps[0]), 110);
  }
  if (label === "Pursue") {
    return "Open the city listing and assign an estimator";
  }
  if (label === "Review") {
    return "Check the concern before spending bid time";
  }
  return "Keep an eye on it for updates or a better fit";
}

function fitConfidenceText(item, trace = null) {
  const label = decisionLabel(item.label);
  const activeTrace = trace || normalizedBidFitnessTrace(item, getStructuredRequirements(item));
  const score = Number(item.rank_score);
  if (label === "Skip") {
    return "Not a fit";
  }
  if (activeTrace.positiveSignals.length >= 2 || score >= 70) {
    return "Strong scope match";
  }
  if (label === "Review") {
    return "Good fit, check first";
  }
  if (label === "Monitor") {
    return "Relevant, not urgent";
  }
  return "Needs a closer look";
}

function whyMatchedItems(item, trace, requirements, brief = null) {
  return firstItems(uniqueTextItems([
    ...briefReasonItems(brief),
    ...requirementSignalItems(requirements),
    ...trace.positiveSignals,
    ...firstItems(item.matched_terms, 4).map((term) => `Matched term: ${term}`)
  ]), 4);
}

function blockerItems(item, trace, brief) {
  return firstItems(uniqueTextItems([
    ...trace.hardBlockers,
    ...trace.softWarnings,
    ...capacityWarningItems(item),
    ...textItems(item.rejection_reasons),
    ...textItems(item.missing_requirements).map((requirement) => `Missing requirement: ${requirement}`),
    ...textItems(brief && (brief.blockers || brief.missing_items))
  ]), 5);
}

function documentItems(item, requirements, brief) {
  return firstItems(uniqueTextItems([
    ...textItems(brief && brief.required_documents),
    ...textItems(requirements && requirements.documents),
    ...textItems(item && item.required_documents)
  ]), 5);
}

function compactSentenceList(items, fallback, limit = 2, maxLength = 220) {
  const safeItems = firstItems(uniqueTextItems(textItems(items).map(cleanDisplayText)), limit);
  if (!safeItems.length) {
    return fallback;
  }
  return shortText(cleanDisplayText(safeItems.join("; ")), maxLength);
}

function fullSentenceList(items, fallback, limit = 4) {
  const safeItems = firstItems(uniqueTextItems(textItems(items).map(cleanDisplayText)), limit);
  return safeItems.length ? cleanDisplayText(safeItems.join("; ")) : fallback;
}

function finalReason(item, requirements) {
  const assessment = getCapacityAssessment(item);
  const rejectionReasons = firstItems(item.rejection_reasons, 2);
  if (decisionLabel(item.label) === "Skip" && rejectionReasons.length) {
    return `Reason to pass: ${rejectionReasons.join(", ")}`;
  }
  if (assessment && assessment.recommended_action === "Pursue After Review") {
    return `Capacity check: ${ownerText(assessment.recommended_action)}`;
  }
  if (requirements && requirements.next_action) {
    return `Next step: ${requirements.next_action}`;
  }
  const reasons = item.reasons || item.rejection_reasons || [];
  if (reasons.length) {
    return reasons[0];
  }
  const label = decisionLabel(item.label);
  if (label === "Pursue") {
    return "Strong enough to look at today.";
  }
  if (label === "Review") {
    return "Potential fit, but check one concern first.";
  }
  if (label === "Skip") {
    return "Probably not worth your bid time.";
  }
  return "Relevant, but not urgent enough for today.";
}

function getCapacityAssessment(item) {
  if (!item || !item.capacity_assessment) {
    return null;
  }
  return item.capacity_assessment;
}

function capacitySummary(item) {
  const assessment = getCapacityAssessment(item);
  if (!assessment) {
    return "";
  }
  return `Capacity: ${assessment.pursuit_load} load, ${assessment.response_capacity.toLowerCase()}, ${assessment.execution_capacity.toLowerCase()}.`;
}

function capacityWarningItems(item) {
  const assessment = getCapacityAssessment(item);
  if (!assessment || !Array.isArray(assessment.warnings)) {
    return [];
  }
  return firstItems(assessment.warnings, 2);
}

function firstPresent(values) {
  return values.find((value) => hasDisplayValue(value));
}

function singleText(value) {
  return textItems(value)[0] || "";
}

function textItems(value) {
  if (!hasDisplayValue(value)) {
    return [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => textItems(item));
  }
  if (isPlainObject(value)) {
    return Object.entries(value).map(([key, entry]) => (
      `${titleCase(humanizeToken(key))}: ${formatTraceValue(entry)}`
    ));
  }
  return [String(value).trim()].filter(Boolean);
}

function uniqueTextItems(items) {
  const seen = new Set();
  return textItems(items).filter((item) => {
    const key = item.toLowerCase();
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function hasDisplayValue(value) {
  if (value === undefined || value === null) {
    return false;
  }
  if (Array.isArray(value)) {
    return value.some((item) => hasDisplayValue(item));
  }
  if (isPlainObject(value)) {
    return Object.values(value).some((item) => hasDisplayValue(item));
  }
  return String(value).trim() !== "";
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function formatTraceValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => formatTraceValue(item)).filter(Boolean).join(", ");
  }
  if (isPlainObject(value)) {
    return Object.entries(value)
      .map(([key, entry]) => `${titleCase(humanizeToken(key))}: ${formatTraceValue(entry)}`)
      .join("; ");
  }
  return String(value ?? "").trim();
}

function firstItems(items, limit) {
  if (Array.isArray(items)) {
    return items.filter(Boolean).slice(0, limit);
  }
  return items ? [items].slice(0, limit) : [];
}

function humanList(items) {
  const values = textItems(items);
  if (!values.length) {
    return "";
  }
  if (values.length === 1) {
    return values[0];
  }
  if (values.length === 2) {
    return `${values[0]} and ${values[1]}`;
  }
  return `${values.slice(0, -1).join(", ")}, and ${values[values.length - 1]}`;
}

function humanizeToken(value) {
  return String(value || "").replace(/[_-]+/g, " ").trim();
}

function runtimePathLabel(metrics) {
  if (!metrics) {
    return "Pending";
  }
  return `${metrics.engine || "python"} / ${metrics.brief_mode || "bid briefs"}`;
}

function runtimePathDetail(metrics) {
  if (!metrics) {
    return "Waiting for scan metrics.";
  }
  return `Engine ${metrics.engine || "python"}; briefs ${metrics.brief_mode || "deterministic_bid_brief"}; portfolio ${metrics.portfolio_mode || "greedy_capacity_optimizer"}.`;
}

function formatStatus(value) {
  if (!value) {
    return "unknown";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "object") {
    if (Object.prototype.hasOwnProperty.call(value, "mode") && Object.prototype.hasOwnProperty.call(value, "available")) {
      return value.available ? value.mode : `${value.mode || "local"} unavailable`;
    }
    if (value.mode && value.fallback) {
      if (value.fallback === "none") {
        return value.mode;
      }
      return value.mode === value.fallback ? value.fallback : `${value.mode}, fallback ready`;
    }
    return value.status || value.mode || value.name || JSON.stringify(value);
  }
  return String(value);
}

function compactRuntimeStatus(value) {
  const formatted = formatStatus(value);
  const normalized = formatted.toLowerCase();
  if (normalized.includes("deterministic")) {
    return "deterministic";
  }
  return shortText(formatted, 18);
}

function runtimeStatusDetail(value) {
  if (!value || typeof value !== "object") {
    return formatStatus(value);
  }
  if (Object.prototype.hasOwnProperty.call(value, "mode") && Object.prototype.hasOwnProperty.call(value, "available")) {
    return value.available
      ? `${humanizeToken(value.mode)} is available.`
      : `${humanizeToken(value.mode)} is unavailable.`;
  }
  return formatStatus(value);
}

function formatMoney(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(amount);
}

function number(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat("en-CA").format(amount);
}

function titleCase(value) {
  return String(value || "").replace(/\w\S*/g, (word) => (
    word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
  ));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

let toastTimer = 0;
function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toast.classList.remove("visible");
  }, 2800);
}
