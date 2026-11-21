/** Credit pack selection and plan history. No payment is collected here. */
import { getApps } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";
import {
  getFirestore,
  collection,
  query,
  where,
  getDocs,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js";

export const CREDIT_PACKS = {
  starter: { packId: "starter", packName: "Starter", credits: 10, listPricePhp: 49 },
  grower: { packId: "grower", packName: "Grower", credits: 25, listPricePhp: 99 },
  season: { packId: "season", packName: "Season", credits: 50, listPricePhp: 149 },
};

const PACK_BY_CREDITS = {
  10: CREDIT_PACKS.starter,
  25: CREDIT_PACKS.grower,
  50: CREDIT_PACKS.season,
};

function firestoreDb() {
  if (!window.TOMATO_INSIGHT_FIREBASE_CONFIG?.projectId || !getApps().length) return null;
  return getFirestore(getApps()[0]);
}

function currentUid() {
  const apps = getApps();
  return apps.length ? getAuth(apps[0]).currentUser?.uid || null : null;
}

export function packFor(packIdOrCredits) {
  if (packIdOrCredits && CREDIT_PACKS[packIdOrCredits]) return CREDIT_PACKS[packIdOrCredits];
  return PACK_BY_CREDITS[Number.parseInt(packIdOrCredits, 10)] || null;
}

export function formatPhp(amount) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return "₱0";
  const rounded = Math.round(n * 100) / 100;
  return Number.isInteger(rounded) ? `₱${rounded}` : `₱${rounded.toFixed(2)}`;
}

export const formatUsd = formatPhp;

export async function listPaymentsForCurrentUser() {
  const uid = currentUid();
  const db = firestoreDb();
  if (!uid || !db) return [];
  const snap = await getDocs(query(collection(db, "payments"), where("uid", "==", uid)));
  const rows = snap.docs.map((item) => ({ id: item.id, ...item.data() }));
  rows.sort((a, b) => Number(b.createdAtMs || 0) - Number(a.createdAtMs || 0));
  return rows;
}

let selecting = false;

/** Select a demo pack and grant its credits immediately. */
export async function selectPlan(packIdOrCredits) {
  const pack = packFor(packIdOrCredits);
  if (!pack || selecting) return;
  selecting = true;
  const buttons = [...document.querySelectorAll("[data-credit-pack]")];
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const addCredits = window.TomatoInsightCredits?.addTopUpCredits;
    if (!addCredits) throw new Error("Credits are still loading. Try again in a moment.");
    const result = await addCredits(pack.credits, {
      ...pack,
      amountChargedPhp: 0,
      method: "plan_selection",
      isDemo: true,
    });
    if (!result?.ok) throw new Error(result?.error || "Could not add credits.");
    window.TomatoInsightCredits?.hideOutOfCreditModal?.();
    window.dispatchEvent(new CustomEvent("tomatoInsight:paymentCompleted", {
      detail: { payment: result.payment, packId: pack.packId, balance: result.balance },
    }));
  } catch (error) {
    console.warn("[TomatoInsight] Plan selection failed.", error);
    window.TomatoInsightCredits?.showCreditToast?.(
      error?.message || "Could not add credits. Try again.", "info"
    );
  } finally {
    selecting = false;
    buttons.forEach((button) => { button.disabled = false; });
  }
}

window.TomatoInsightPayments = {
  CREDIT_PACKS,
  packFor,
  formatPhp,
  formatUsd,
  selectPlan,
  listPaymentsForCurrentUser,
};
