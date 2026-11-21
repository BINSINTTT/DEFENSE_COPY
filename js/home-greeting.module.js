import { getApps } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import { getAuth, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";
import { loadUserProfile } from "./Firebase/user-profile.service.module.js";

function homeFarmName(profile) {
  return profile?.farmName?.trim() || "Your farm";
}

async function refreshHomeGreeting(user) {
  const el = document.getElementById("home-welcome-name");
  if (!el || !user) return;

  const profile = await loadUserProfile(user.uid, user);
  el.textContent = homeFarmName(profile);
}

function initHomeGreeting() {
  const apps = getApps();
  if (!apps.length) return;

  const auth = getAuth(apps[0]);

  onAuthStateChanged(auth, (user) => {
    if (user) refreshHomeGreeting(user);
  });

  window.addEventListener("tomatoInsight:userDataReady", (event) => {
    const shouldRefresh = window.TomatoInsightUserData?.shouldRefreshUiForUserDataEvent?.(
      event.detail
    );
    if (shouldRefresh === false) return;
    const user = auth.currentUser;
    if (user) refreshHomeGreeting(user);
  });

  window.addEventListener("tomatoInsight:profileUpdated", () => {
    const user = auth.currentUser;
    if (user) refreshHomeGreeting(user);
  });
}

initHomeGreeting();
