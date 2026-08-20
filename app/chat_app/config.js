/* Assad Motors — standalone chat app configuration (Phase 11A).
   Every dealership-specific detail lives here. Change this file only —
   no need to touch app.js / style.css / index.html. */
window.DEALER_CONFIG = {
  name: "Assad Motors",
  tagline: "Premium Pre-Owned Cars",

  // Contact links (top-right header buttons)
  phone: "tel:+919029664381",
  whatsapp: "https://wa.me/919029664381",
  instagram: "https://www.instagram.com/assad_motors/",

  // Logo image URL. Leave null to show the initials placeholder.
  logo: null,

  // Welcome screen
  greeting: "Welcome to Assad Motors",
  subGreeting: "How can I help you today?",
  // Opening one-click filter chips. Each chip shows a friendly `label` but sends
  // the exact `q` text to the SAME existing /chat backend — no separate filter
  // system. Every `q` was verified against the live inventory to return the
  // correct, exact-filtered, cheapest-first cars (counts at time of writing:
  // 7-seat 33, 5-seat 115, CNG 23, Petrol 89, Diesel 74, Automatic 56, Manual
  // 131, Luxury 28, Sunroof 2, <2L 32, <5L 105, <10L 157, <40k km 2). The plural
  // "cars" / spelled-out band wording is what marks each as a search.
  suggestions: [
    { label: "7 Seater",        q: "7 seater" },
    { label: "5 Seater",        q: "5 seater" },
    { label: "CNG Cars",        q: "cng cars" },
    { label: "Petrol Cars",     q: "petrol cars" },
    { label: "Diesel Cars",     q: "diesel cars" },
    { label: "Automatic Cars",  q: "automatic cars" },
    { label: "Manual Cars",     q: "manual cars" },
    { label: "Luxury Cars",     q: "luxury cars" },
    { label: "Sunroof Cars",    q: "sunroof cars" },
    { label: "Under ₹2 Lakh",   q: "under 2 lakh" },
    { label: "Under ₹5 Lakh",   q: "under 5 lakh" },
    { label: "Under ₹10 Lakh",  q: "under 10 lakh" },
    { label: "Under 40,000 KM", q: "under 40000 km" }
  ],

  inputPlaceholder: "Ask anything about our cars...",
  footer: "Powered by Assad Motors AI",

  // Backend /chat API base URL.
  //  - "" (empty)      → same origin as the page (production: chat.assadmotors.com behind Nginx)
  //  - full URL        → e.g. "http://localhost:8000"
  //  - auto (default)  → same host the page was opened from, port 8000
  //    (works on the laptop AND on phones opening the LAN IP)
  apiUrl: "http://" + (location.hostname || "localhost") + ":8000"
};
