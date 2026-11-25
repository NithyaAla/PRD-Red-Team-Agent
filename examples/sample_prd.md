# RefillRx: AI Prescription Refill Assistant on WhatsApp

**Owner:** Product, Chronic Care Pod
**Status:** Ready for engineering
**Target launch:** 15 January 2027

## 1. Background

Our pharmacy app has 2 million monthly active users in India, and 38% of orders are repeat orders for chronic conditions such as diabetes, hypertension and thyroid disorders. Users frequently forget to reorder and run out of medicines. Elderly users in particular find the app hard to use and prefer WhatsApp.

## 2. Goals

- Make reordering chronic medicines effortless.
- Move repeat orders from the app to WhatsApp, where our users already are.
- Use AI to remove manual steps from the refill journey.

## 3. Solution overview

Users send a photo of their prescription to our WhatsApp Business number. An LLM (GPT-class model via a third-party API) reads the image, extracts the medicine names, strengths and dosage, and creates a refill schedule. Before the user runs out, RefillRx automatically places the order and charges the user through UPI Autopay. The medicines are delivered to the saved address.

## 4. User stories

1. As a patient, I can send a prescription photo on WhatsApp and get my medicines without opening the app.
2. As a patient, I get my refills automatically every month without having to remember.
3. As a patient, I can reply "STOP" to pause refills.
4. As a caregiver, I can manage refills for my parents from my own WhatsApp number.

## 5. Functional requirements

- FR1: The system accepts prescription images (JPG, PNG) up to 10 MB on WhatsApp.
- FR2: The LLM extracts medicine name, strength, frequency and duration. OCR accuracy should be high.
- FR3: Extracted medicines are matched against our catalogue and the order is created automatically. Schedule H and H1 drugs are included so that patients on antibiotics and other prescription drugs also benefit.
- FR4: To verify identity, users share their Aadhaar number on WhatsApp at onboarding. We store it in the user profile.
- FR5: Refill date = last order date + (quantity / daily dose) minus 3 days.
- FR6: Payment is collected via UPI Autopay mandate set up once at onboarding, with a maximum mandate amount of Rs 15,000 per debit.
- FR7: The user's WhatsApp phone number is their account. Any message from that number is treated as the account holder.
- FR8: Responses to the user should be real-time.
- FR9: Caregivers can add up to 5 family members by sending their names and prescriptions.

## 6. Data

All prescription images and extracted data will be stored in our S3 bucket indefinitely so we can use them for model improvement and analytics. Extracted data is also sent to our marketing data warehouse for personalised offers.

## 7. Non-functional requirements

- The system should be fast and scalable.
- The system should be secure.
- Availability: same as our existing app.

## 8. Dependencies

- WhatsApp Business API (via our existing BSP partner).
- Third-party LLM API for prescription reading.
- Inventory availability API from the supply chain team: TBD, the team says it will be ready before launch.

## 9. Success metrics

- Users love the experience.
- Increase engagement on WhatsApp.
- Reduce churn among chronic patients.

## 10. Launch plan

We will launch to all 2 million users on 15 January with a push notification and WhatsApp broadcast. Engineering team: 2 backend engineers and 1 mobile engineer, starting 20 December.

## 11. Out of scope

- Hindi and other regional languages (English only for v1).
- Pharmacist review (the AI handles extraction, which is the bottleneck today).
