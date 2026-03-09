**[PolicyEngine](https://policyengine.org)** is a nonprofit with the mission to **compute the impact of public policy for the world.**

## What we do

Our free, open-source software models the tax and benefit systems in the US and UK, using our microsimulation framework based on [OpenFisca](https://openfisca.org). We enhance representative survey microdata for macroeconomic analysis and make everything available as Python packages, APIs, or web apps.

The PolicyEngine web app lets users design custom tax-benefit reforms and see how they would affect the population (budget, poverty, and inequality) and individual households (net income and marginal tax rates). Users can also estimate their tax liability and benefit eligibility under current law.

## Highlights

- **Government use**: Our co-founder and CTO Nikhil Woodruff spent six months as an [Innovation Fellow at 10 Downing Street](https://fellows.ai.gov.uk/articles/nikhil-woodruff-micro-simulation), adapting PolicyEngine for UK government policy analysis
- **NBER partnership**: We're building an [open-source TAXSIM emulator](https://policyengine.org/us/research/policyengine-nber-mou-taxsim) in collaboration with the National Bureau of Economic Research
- **Atlanta Fed partnership**: We're integrating the [Policy Rules Database](https://policyengine.org/us/research/policyengine-atlanta-fed-mou-prd) for multi-model validation across tax and benefit programs
- **State coverage**: We model income taxes for all 50 US states plus DC, along with major federal and state benefit programs
- **AI-powered explanations**: Our [AI system](https://policyengine.org/uk/research/uk-household-ai) translates complex tax and benefit calculations into plain language

## Core repositories

We welcome contributions to our repositories, especially our core ones:

**Country models**
- [`policyengine-us`](https://github.com/PolicyEngine/policyengine-us) — US tax-benefit microsimulation model (Python)
- [`policyengine-uk`](https://github.com/PolicyEngine/policyengine-uk) — UK tax-benefit microsimulation model (Python)
- [`policyengine-canada`](https://github.com/PolicyEngine/policyengine-canada) — Canada tax-benefit microsimulation model (Python)

**Infrastructure**
- [`policyengine-core`](https://github.com/PolicyEngine/policyengine-core) — Microsimulation framework (Python)
- [`policyengine-app`](https://github.com/PolicyEngine/policyengine-app) — Web application (React)
- [`policyengine-api`](https://github.com/PolicyEngine/policyengine-api) — REST API (Python)

**Data and validation**
- [`policyengine-us-data`](https://github.com/PolicyEngine/policyengine-us-data) — Enhanced US microdata with ML-based imputation
- [`policyengine-uk-data`](https://github.com/PolicyEngine/policyengine-uk-data) — Enhanced UK microdata with local area estimates
- [`policyengine-taxsim`](https://github.com/PolicyEngine/policyengine-taxsim) — NBER TAXSIM emulator

**Utilities**
- [`microdf`](https://github.com/PolicyEngine/microdf) — Weighted pandas DataFrames for survey microdata analysis
- [`policyengine.py`](https://github.com/PolicyEngine/policyengine.py) — Python client for the PolicyEngine API

## Supported by

[Arnold Ventures](https://www.arnoldventures.org/) • [Nuffield Foundation](https://www.nuffieldfoundation.org/) • [NEO Philanthropy](https://neophilanthropy.org/) • [Gerald Huff Fund for Humanity](https://fundforhumanity.org/) • [PSL Foundation](http://psl-foundation.org)

## Learn more

- [policyengine.org](https://policyengine.org) — Try our calculator
- [Research](https://policyengine.org/us/research) — Policy analysis and blog posts
- [API documentation](https://householdapi.policyengine.org/docs) — Build with our API
- [Contact](mailto:hello@policyengine.org) — Get in touch
