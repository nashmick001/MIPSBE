# DropMtaani in-app chatbot — baseline before the Meta hackathon

Date: 2026-10-27

This records what the pre-existing in-app chatbot could and could not do before
any hackathon work began. Plain-language capabilities only. The new agent
replaces it behind the same chat screen.

## Before the Meta hackathon, the DropMtaani in-app chatbot could:

- Hold text conversations, remembering recent turns within the same conversation
- Search products and stores, showing results as tappable cards with prices
- Add items to the cart, remove items, and change quantities (the app cart updated to match)
- Show categories, best deals, and popular items
- Answer questions about ride options, estimated fares, and past trips
- Answer questions about rental vehicles and service providers
- Recall the customer's stated preferences from their profile during the conversation (partially — used for personalization, not for pre-filling orders)
- Serve both logged-in customers and guests
- Keep a list of past conversations that could be reopened or deleted
- Limit message frequency to prevent abuse
- Respond in the customer's language when that language was enabled on the platform (partially — English verified, Kiswahili not verified)
- Ask the customer to pick a shopping section when none was selected

## It could NOT:

- Place an order or check out
- Start, confirm, or track an M-Pesa payment
- Track an order's delivery status
- Accept voice notes or transcribe speech
- Accept customer photos or analyze images
- Predict or pre-fill a cart from order history
- Understand Sheng (not verified — no Sheng support found)
- Hand off to a human agent
- Defend against prompt-injection attempts
- Answer in a language not enabled on the platform (it declined instead)

## Model and provider

- Provider: OpenAI, called from the DropMtaani servers
- Model: gpt-4o, using tool/function calling for searches, catalog lookups, and cart changes
