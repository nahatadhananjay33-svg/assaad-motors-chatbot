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
  suggestions: [
    "Looking for an SUV",
    "Cars under ₹10 lakh",
    "Show Honda City",
    "Finance options",
    "Automatic cars",
    "Diesel cars",
    "Petrol cars",
    "Luxury cars"
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
