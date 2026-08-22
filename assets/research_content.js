// Curated content for the Research tab. This is written/reviewed content, not a live feed —
// "predicting outperformance" isn't something a free API does reliably, so this is meant to be
// periodically refreshed by asking an LLM (or your own research) to update SECTOR_THEMES below,
// updating LAST_REVIEWED each time. Company lists are deliberately limited to large, well-known
// listed names as illustrative examples of a theme — not a ranked "buy list".

const LAST_REVIEWED = "22-Aug-2026";

const SECTOR_THEMES = [
  {
    sector: "Banking & Financial Services",
    thesis:
      "Credit growth tends to track nominal GDP growth in India, and private banks + large NBFCs have historically compounded book value as formal-credit penetration rises. Rate-cut cycles (like the current accommodative stance) typically support both margins and loan demand with a lag.",
    companies: ["HDFC Bank", "ICICI Bank", "Bajaj Finance", "State Bank of India"],
  },
  {
    sector: "Capital Goods & Infrastructure",
    thesis:
      "Sustained government capex on roads, railways, and power transmission, plus a private capex upcycle, tends to benefit engineering, cement, and construction-linked names over multi-year infrastructure build-outs.",
    companies: ["Larsen & Toubro", "UltraTech Cement", "Siemens India", "Cummins India"],
  },
  {
    sector: "Manufacturing & PLI-linked Industries",
    thesis:
      "Production-Linked Incentive schemes across electronics, specialty chemicals, and defence manufacturing aim to shift a share of global supply chains toward India — a multi-year theme rather than a quarterly one.",
    companies: ["Bharat Electronics", "Tata Electronics", "Dixon Technologies", "Solar Industries"],
  },
  {
    sector: "Renewable Energy & Green Transition",
    thesis:
      "India's renewable capacity targets and grid/storage buildout support utilities and equipment makers tied to solar, wind, and transmission — a structural theme tied to national energy-transition policy rather than a single budget cycle.",
    companies: ["NTPC", "Tata Power", "Adani Green Energy", "Power Grid Corporation"],
  },
  {
    sector: "Healthcare & Pharmaceuticals",
    thesis:
      "Domestic formulation growth, hospital-bed capacity additions, and a steady generics/specialty export pipeline give this sector a defensive-growth character less tied to the broader economic cycle.",
    companies: ["Sun Pharma", "Apollo Hospitals", "Cipla", "Dr. Reddy's Laboratories"],
  },
  {
    sector: "IT Services & Digital",
    thesis:
      "Global enterprise IT/cloud/AI-transformation spend is the swing factor here — a slower-growth but cash-generative sector that tends to re-rate when discretionary tech budgets recover.",
    companies: ["Tata Consultancy Services", "Infosys", "HCLTech", "Persistent Systems"],
  },
  {
    sector: "Consumer Discretionary & Retail",
    thesis:
      "Rising per-capita income and a young population support discretionary categories (retail, QSR, travel) over the long run, though this segment is more sensitive to near-term inflation and rural demand swings than staples.",
    companies: ["Titan Company", "Trent", "Avenue Supermarts (DMart)", "Zomato"],
  },
  {
    sector: "Automobiles & Auto Components",
    thesis:
      "A multi-year replacement cycle plus EV/hybrid transition creates two parallel growth tracks — traditional volume growth and a newer electrification-linked capex cycle for component makers.",
    companies: ["Maruti Suzuki", "Tata Motors", "Bosch India", "Bharat Forge"],
  },
  {
    sector: "Real Estate & Housing Finance",
    thesis:
      "Urbanisation and a multi-year housing upcycle (post the 2020-22 low base) support both developers and the housing-finance lenders that fund homebuyers, with rate cuts acting as an additional tailwind for affordability.",
    companies: ["DLF", "Godrej Properties", "LIC Housing Finance", "Can Fin Homes"],
  },
  {
    sector: "Insurance & Financial Inclusion",
    thesis:
      "Low insurance penetration relative to GDP versus global peers is the core long-term argument here — growth is steady rather than explosive, and tends to compound over a full market cycle.",
    companies: ["HDFC Life Insurance", "ICICI Prudential Life", "SBI Life Insurance", "Star Health Insurance"],
  },
];

if (typeof module !== "undefined") {
  module.exports = { LAST_REVIEWED, SECTOR_THEMES };
}
