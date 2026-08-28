import logging
# pyrefly: ignore [missing-import]
from sqlalchemy import text
# pyrefly: ignore [missing-import]
from sqlalchemy import select
from app.db.session import SessionLocal, engine
from app.db.models import AiTopicCurriculum


logger = logging.getLogger(__name__)


async def ensure_db_columns():
    """Ensure database tables have expected columns."""
    logger.info("Ensuring schema columns exist.")
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS publisher VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS original_url VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR DEFAULT 'user'"
        ))
    logger.info("Schema columns check complete.")


async def seed_admin_user():
    """Create default admin user from env if it doesn't already exist or update credentials."""
    from app.core.config import settings
    from app.core.security import get_password_hash, verify_password
    from app.db.models import User, UserProfile

    logger.info(f"Checking for default admin user: {settings.FIRST_SUPERUSER_EMAIL}")
    async with SessionLocal() as db:
        result = await db.execute(select(User).filter(User.email == settings.FIRST_SUPERUSER_EMAIL))
        admin_user = result.scalars().first()

        if not admin_user:
            admin_user = User(
                full_name=settings.FIRST_SUPERUSER_FULL_NAME,
                email=settings.FIRST_SUPERUSER_EMAIL,
                hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                is_active=True,
                is_verified=True,
                is_superuser=True,
                is_suspended=False,
                role="admin",
            )
            db.add(admin_user)
            await db.flush()  # to populate admin_user.id

            admin_profile = UserProfile(
                user_id=admin_user.id,
                interests=["General AI", "Technology"],
                ai_level="Advanced",
                primary_goal="System Administration",
            )
            db.add(admin_profile)
            await db.commit()
            logger.info(f"Default admin user created successfully: {settings.FIRST_SUPERUSER_EMAIL}")
        else:
            # Ensure full admin privileges & sync password if updated
            updated = False
            if not verify_password(settings.FIRST_SUPERUSER_PASSWORD, admin_user.hashed_password):
                admin_user.hashed_password = get_password_hash(settings.FIRST_SUPERUSER_PASSWORD)
                updated = True
            if not admin_user.is_superuser:
                admin_user.is_superuser = True
                updated = True
            if admin_user.role != "admin":
                admin_user.role = "admin"
                updated = True
            if not admin_user.is_verified:
                admin_user.is_verified = True
                updated = True
            if not admin_user.is_active:
                admin_user.is_active = True
                updated = True
            if admin_user.is_suspended:
                admin_user.is_suspended = False
                updated = True

            if updated:
                await db.commit()
                logger.info(f"Default admin user credentials/privileges updated: {settings.FIRST_SUPERUSER_EMAIL}")
            else:
                logger.info(f"Default admin user already exists with full admin access: {settings.FIRST_SUPERUSER_EMAIL}")



DEFAULT_PRIVACY_POLICY = """# Privacy Policy
*Last Updated: July 2026*

## 1. Information We Collect

### 1.1 Account Information
When you create an account, we may collect:
- Your name or username
- Email address
- Login credentials

This information is used to create and manage your account securely.

### 1.2 Listening and Learning Data
While using the app, we may collect information related to your learning progress, including:
- Completed listening sessions
- Quiz results and scores
- Focus and concentration metrics
- Listening time and activity history
- Achievement badges and progress statistics

This information is used to personalize your experience and track your improvement over time.

### 1.3 Usage Information
We may collect limited information about how you use the app, such as:
- Features and lessons accessed
- Session activity and completion status
- Device type and operating system
- App performance and crash reports

This information helps us improve the app's functionality, performance, and user experience."""

DEFAULT_TERMS_CONDITIONS = """# Terms and Conditions
*Last Updated: July 2026*

## 1. Acceptance of Terms
By creating an account and using the application, you agree to comply with these Terms and Conditions. If you do not agree with any part of these terms, please do not use the app.

## 2. User Accounts
To access certain features of the app, you may be required to create an account. You are responsible for:
- Providing accurate and up-to-date information.
- Maintaining the confidentiality of your login credentials.
- All activities that occur under your account.

You are responsible for keeping your account information secure and notifying us immediately of any unauthorized use.

## 3. Use of the Application
The app is designed to help users improve their focus, concentration, active listening, and memory skills through interactive listening exercises and quizzes.

By using the app, you agree to:
- Use the application only for lawful purposes.
- Not misuse or attempt to interfere with the app's functionality.
- Not copy, distribute, or modify any content without permission.
- Respect the intellectual property rights associated with the application."""

DEFAULT_ACCOUNT_DELETION_POLICY = """# Account Deletion Policy
*Last Updated: July 2026*

## 1. Right to Delete Your Account
You have the right to permanently delete your account and associated personal data at any time through the app settings or by contacting support.

## 2. Data Eradication
Upon processing an account deletion request:
- Your profile credentials and personal identifiers will be permanently removed.
- Your progress records, quiz attempt history, and streak statistics will be erased from active databases.
- Associated temporary security tokens and session records will be invalidated immediately.

## 3. Irreversibility
Once account deletion is confirmed, this action cannot be undone. If you wish to use the service again in the future, a new account must be created."""


async def seed_app_settings():
    """Ensure AppSettings has proper default Markdown text matching mobile app."""
    from app.db.models import AppSettings

    async with SessionLocal() as db:
        res = await db.execute(select(AppSettings).filter(AppSettings.id == 1))
        config = res.scalars().first()

        if not config:
            config = AppSettings(
                id=1,
                support_email="support@todai.app",
                privacy_policy=DEFAULT_PRIVACY_POLICY,
                terms_conditions=DEFAULT_TERMS_CONDITIONS,
                account_deletion_policy=DEFAULT_ACCOUNT_DELETION_POLICY,
            )
            db.add(config)
            await db.commit()
            logger.info("Seeded initial AppSettings with mobile app default policies.")
        else:
            # If current values are generic placeholders, update to official app markdown content
            updated = False
            if not config.privacy_policy or "here" in config.privacy_policy or len(config.privacy_policy) < 50:
                config.privacy_policy = DEFAULT_PRIVACY_POLICY
                updated = True
            if not config.terms_conditions or "here" in config.terms_conditions or len(config.terms_conditions) < 50:
                config.terms_conditions = DEFAULT_TERMS_CONDITIONS
                updated = True
            if not config.account_deletion_policy or "instructions" in config.account_deletion_policy or len(config.account_deletion_policy) < 50:
                config.account_deletion_policy = DEFAULT_ACCOUNT_DELETION_POLICY
                updated = True


            if updated:
                await db.commit()
                logger.info("Updated AppSettings generic placeholders to official mobile app policies.")


async def seed_curriculum():
    """
    Populate the ai_topic_curriculum table with 60 structured AI concepts.
    Safe to call on every startup — only inserts topics that don't already exist (by slug).
    """
    TOPICS = [
        # ─── BEGINNER (seq 1–20) ───────────────────────────────────────────────
        {
            "slug": "what-is-ai",
            "title": "What is Artificial Intelligence?",
            "description": "A foundational introduction to AI — what it is, what it isn't, and why it matters today.",
            "level": "Beginner", "category": "Foundations", "sequence_order": 1,
            "search_keywords": ["artificial intelligence basics", "what is AI", "AI explained"],
            "learning_objectives": ["Define AI in plain language", "Distinguish AI from regular software", "Name 3 everyday AI applications"],
        },
        {
            "slug": "ai-vs-ml-vs-dl",
            "title": "AI vs Machine Learning vs Deep Learning",
            "description": "Understand how AI, ML, and deep learning relate to each other and where each term applies.",
            "level": "Beginner", "category": "Foundations", "sequence_order": 2,
            "search_keywords": ["machine learning vs AI", "deep learning explained", "AI hierarchy"],
            "learning_objectives": ["Explain the difference between AI, ML, and DL", "Identify which category a given system belongs to"],
        },
        {
            "slug": "how-ml-works",
            "title": "How Machine Learning Actually Works",
            "description": "A plain-language explanation of training, data, and predictions — the core loop of ML.",
            "level": "Beginner", "category": "Foundations", "sequence_order": 3,
            "search_keywords": ["how machine learning works", "training data AI", "ML model prediction"],
            "learning_objectives": ["Describe the training loop in simple terms", "Understand what a model is", "Explain supervised learning with an example"],
        },
        {
            "slug": "neural-networks-basics",
            "title": "Neural Networks: The Brain Behind AI",
            "description": "What neural networks are, why they're inspired by the human brain, and how they process information.",
            "level": "Beginner", "category": "Models", "sequence_order": 4,
            "search_keywords": ["neural networks explained", "deep neural network basics", "AI neurons"],
            "learning_objectives": ["Describe what a neuron does in an AI context", "Understand layers in a neural network", "Explain why more layers = deeper learning"],
        },
        {
            "slug": "what-is-chatgpt",
            "title": "What is ChatGPT and How Does It Work?",
            "description": "A beginner's guide to ChatGPT — how it was trained, what it can do, and its limitations.",
            "level": "Beginner", "category": "Models", "sequence_order": 5,
            "search_keywords": ["ChatGPT explained", "OpenAI ChatGPT", "how ChatGPT works"],
            "learning_objectives": ["Explain what ChatGPT is in simple terms", "Describe how language models are trained", "Identify 3 use cases and 2 limitations"],
        },
        {
            "slug": "what-are-llms",
            "title": "Large Language Models (LLMs) Explained",
            "description": "What LLMs are, why they're transforming AI, and how they understand and generate language.",
            "level": "Beginner", "category": "Models", "sequence_order": 6,
            "search_keywords": ["large language models", "LLM explained", "GPT model"],
            "learning_objectives": ["Define what an LLM is", "Explain token-based language generation", "Name 3 major LLMs and their makers"],
        },
        {
            "slug": "what-is-generative-ai",
            "title": "Generative AI: Creating Content with AI",
            "description": "How generative AI creates text, images, code, and more — and what makes it different from earlier AI.",
            "level": "Beginner", "category": "Applications", "sequence_order": 7,
            "search_keywords": ["generative AI", "AI content creation", "text to image AI"],
            "learning_objectives": ["Define generative AI", "List 4 types of content generative AI can create", "Understand what 'foundation model' means"],
        },
        {
            "slug": "prompt-engineering-intro",
            "title": "Prompt Engineering: Talking to AI Effectively",
            "description": "How to write better prompts to get better results from AI tools — a practical beginner skill.",
            "level": "Beginner", "category": "Applications", "sequence_order": 8,
            "search_keywords": ["prompt engineering", "better AI prompts", "how to use ChatGPT effectively"],
            "learning_objectives": ["Explain what a prompt is", "Apply 3 prompt improvement techniques", "Understand zero-shot vs few-shot prompting"],
        },
        {
            "slug": "ai-in-everyday-life",
            "title": "AI in Everyday Life: Where You Already Use It",
            "description": "Discover the AI hidden in your daily apps — from streaming recommendations to spam filters.",
            "level": "Beginner", "category": "Applications", "sequence_order": 9,
            "search_keywords": ["AI everyday life", "AI applications consumer", "AI recommendation systems"],
            "learning_objectives": ["Identify 5 AI applications you use daily", "Understand how recommendation systems work", "Recognize AI-powered features in products"],
        },
        {
            "slug": "ai-bias-fairness",
            "title": "AI Bias: When AI Gets It Wrong",
            "description": "Why AI systems can be unfair, where bias comes from, and what's being done to address it.",
            "level": "Beginner", "category": "Safety", "sequence_order": 10,
            "search_keywords": ["AI bias", "algorithmic fairness", "AI discrimination"],
            "learning_objectives": ["Explain what AI bias is and where it comes from", "Give 2 real-world examples of AI bias", "Understand what fairness means in AI context"],
        },
        {
            "slug": "supervised-unsupervised-learning",
            "title": "Supervised vs Unsupervised Learning",
            "description": "The two core learning paradigms in ML — when each is used and how they differ.",
            "level": "Beginner", "category": "Foundations", "sequence_order": 11,
            "search_keywords": ["supervised learning", "unsupervised learning examples", "ML learning types"],
            "learning_objectives": ["Define supervised and unsupervised learning", "Give an example of each", "Understand when to use each approach"],
        },
        {
            "slug": "ai-image-generation",
            "title": "AI Image Generation: How Computers Draw",
            "description": "How models like DALL-E and Midjourney create images from text — the tech behind the magic.",
            "level": "Beginner", "category": "Applications", "sequence_order": 12,
            "search_keywords": ["AI image generation", "DALL-E Midjourney", "text to image AI model"],
            "learning_objectives": ["Explain how diffusion models generate images", "Understand what text-to-image means", "Name 3 major image generation tools"],
        },
        {
            "slug": "ai-in-healthcare",
            "title": "AI in Healthcare: Saving Lives with Data",
            "description": "How AI is being used to diagnose diseases, discover drugs, and improve patient outcomes.",
            "level": "Beginner", "category": "Applications", "sequence_order": 13,
            "search_keywords": ["AI healthcare", "medical AI", "AI drug discovery"],
            "learning_objectives": ["Identify 3 major healthcare AI applications", "Understand AI-assisted diagnosis", "Explain why medical AI requires special care"],
        },
        {
            "slug": "ai-in-business",
            "title": "How Businesses Are Using AI Today",
            "description": "A practical survey of how companies across industries are deploying AI to save time and money.",
            "level": "Beginner", "category": "Business", "sequence_order": 14,
            "search_keywords": ["AI business applications", "enterprise AI", "AI automation"],
            "learning_objectives": ["List 5 business AI use cases", "Understand ROI of AI tools", "Distinguish automation from AI decision-making"],
        },
        {
            "slug": "ai-tools-overview",
            "title": "The AI Tools Landscape: What's Available Now",
            "description": "A curated overview of the most important AI tools available today and what each is best for.",
            "level": "Beginner", "category": "Applications", "sequence_order": 15,
            "search_keywords": ["best AI tools", "AI software 2025", "top AI apps"],
            "learning_objectives": ["Name the major AI tool categories", "Match tools to use cases", "Understand the difference between foundation models and AI products"],
        },
        {
            "slug": "natural-language-processing",
            "title": "Natural Language Processing: Teaching AI to Read",
            "description": "How computers learn to understand and generate human language — the field behind chatbots and voice assistants.",
            "level": "Beginner", "category": "Foundations", "sequence_order": 16,
            "search_keywords": ["natural language processing NLP", "NLP AI explained", "sentiment analysis AI"],
            "learning_objectives": ["Define NLP and its core tasks", "Explain how tokenization works", "Identify 3 everyday NLP applications"],
        },
        {
            "slug": "computer-vision-basics",
            "title": "Computer Vision: Teaching AI to See",
            "description": "How AI systems recognize objects, faces, and scenes in images and video.",
            "level": "Beginner", "category": "Foundations", "sequence_order": 17,
            "search_keywords": ["computer vision AI", "image recognition", "object detection AI"],
            "learning_objectives": ["Define computer vision", "Explain how image classifiers work", "List 3 real-world applications"],
        },
        {
            "slug": "ai-ethics-intro",
            "title": "AI Ethics: Why How We Build AI Matters",
            "description": "The ethical principles guiding responsible AI development — transparency, accountability, and fairness.",
            "level": "Beginner", "category": "Safety", "sequence_order": 18,
            "search_keywords": ["AI ethics", "responsible AI", "ethical AI development"],
            "learning_objectives": ["List the core AI ethics principles", "Explain why AI ethics matters", "Give an example of an unethical AI decision"],
        },
        {
            "slug": "ai-vs-human-intelligence",
            "title": "AI vs Human Intelligence: Key Differences",
            "description": "What AI is genuinely better at, where humans still win, and why the comparison is often misleading.",
            "level": "Beginner", "category": "Foundations", "sequence_order": 19,
            "search_keywords": ["AI vs human intelligence", "can AI think", "AGI human comparison"],
            "learning_objectives": ["Identify 5 tasks AI outperforms humans at", "Identify 5 tasks humans outperform AI at", "Understand the concept of narrow vs general AI"],
        },
        {
            "slug": "future-of-ai-beginner",
            "title": "The Future of AI: What to Expect Next",
            "description": "A grounded, beginner-friendly look at where AI is heading in the next 5–10 years.",
            "level": "Beginner", "category": "Foundations", "sequence_order": 20,
            "search_keywords": ["future of AI", "AI 2025 trends", "AI predictions"],
            "learning_objectives": ["Describe 3 near-term AI trends", "Understand what AGI means and where it stands", "Identify 2 major challenges facing AI progress"],
        },

        # ─── INTERMEDIATE (seq 21–40) ─────────────────────────────────────────
        {
            "slug": "transformers-architecture",
            "title": "Transformers: The Architecture Behind Modern AI",
            "description": "How the Transformer architecture works — the breakthrough that made GPT and BERT possible.",
            "level": "Intermediate", "category": "Models", "sequence_order": 21,
            "search_keywords": ["transformer architecture", "attention mechanism AI", "BERT GPT transformer"],
            "learning_objectives": ["Explain what a Transformer is", "Understand the self-attention mechanism", "Describe why Transformers beat RNNs"],
        },
        {
            "slug": "fine-tuning-llms",
            "title": "Fine-Tuning: Teaching AI Your Specific Domain",
            "description": "How organizations take pre-trained models and adapt them to specific tasks with their own data.",
            "level": "Intermediate", "category": "Models", "sequence_order": 22,
            "search_keywords": ["fine-tuning LLM", "domain specific AI training", "AI model customization"],
            "learning_objectives": ["Define fine-tuning and when it's used", "Contrast fine-tuning with prompting", "Understand what LoRA is and why it's efficient"],
        },
        {
            "slug": "retrieval-augmented-generation",
            "title": "RAG: Giving AI Access to Your Data",
            "description": "Retrieval-Augmented Generation — how to combine LLMs with external knowledge bases to reduce hallucinations.",
            "level": "Intermediate", "category": "Applications", "sequence_order": 23,
            "search_keywords": ["RAG retrieval augmented generation", "LLM knowledge base", "AI hallucination reduction"],
            "learning_objectives": ["Explain what RAG is and why it exists", "Describe the retrieval + generation pipeline", "Understand when RAG is better than fine-tuning"],
        },
        {
            "slug": "embeddings-and-vector-search",
            "title": "Embeddings: How AI Understands Meaning",
            "description": "What vector embeddings are, how they encode semantic meaning, and why they power modern AI search.",
            "level": "Intermediate", "category": "Models", "sequence_order": 24,
            "search_keywords": ["AI embeddings", "vector search AI", "semantic search LLM"],
            "learning_objectives": ["Define an embedding in plain terms", "Explain cosine similarity", "Understand how vector databases work"],
        },
        {
            "slug": "ai-agents",
            "title": "AI Agents: Autonomous AI That Gets Things Done",
            "description": "How AI agents plan, use tools, and execute multi-step tasks without constant human guidance.",
            "level": "Intermediate", "category": "Applications", "sequence_order": 25,
            "search_keywords": ["AI agents autonomous", "LLM agent tools", "AutoGPT AI agent"],
            "learning_objectives": ["Define what an AI agent is", "Explain the ReAct framework (Reason + Act)", "Identify 3 agent use cases and their risks"],
        },
        {
            "slug": "multimodal-ai",
            "title": "Multimodal AI: Beyond Text",
            "description": "How modern AI models process text, images, audio, and video together — and what this enables.",
            "level": "Intermediate", "category": "Models", "sequence_order": 26,
            "search_keywords": ["multimodal AI models", "GPT-4V vision AI", "text image audio AI"],
            "learning_objectives": ["Define multimodal AI", "List 3 multimodal model capabilities", "Explain cross-modal attention"],
        },
        {
            "slug": "ai-hallucinations",
            "title": "AI Hallucinations: Why AI Makes Things Up",
            "description": "Why LLMs generate confident-sounding false information and what techniques reduce this problem.",
            "level": "Intermediate", "category": "Safety", "sequence_order": 27,
            "search_keywords": ["AI hallucinations", "LLM hallucination problem", "AI factual errors"],
            "learning_objectives": ["Explain what hallucination is and why it happens", "Describe 3 mitigation strategies", "Know when to trust AI outputs"],
        },
        {
            "slug": "ai-evaluation-benchmarks",
            "title": "How AI Models Are Evaluated and Compared",
            "description": "The benchmarks, leaderboards, and metrics used to measure AI model quality and capability.",
            "level": "Intermediate", "category": "Models", "sequence_order": 28,
            "search_keywords": ["AI benchmarks", "LLM evaluation metrics", "AI model comparison leaderboard"],
            "learning_objectives": ["Name the major AI benchmarks (MMLU, HumanEval, etc.)", "Understand perplexity and accuracy metrics", "Critique benchmark limitations"],
        },
        {
            "slug": "ai-in-coding",
            "title": "AI for Coding: GitHub Copilot and Beyond",
            "description": "How AI coding assistants work, what they're genuinely good at, and their effect on developer productivity.",
            "level": "Intermediate", "category": "Applications", "sequence_order": 29,
            "search_keywords": ["GitHub Copilot AI", "AI code generation", "AI programming assistant"],
            "learning_objectives": ["Explain how code generation models are trained", "Identify 5 AI coding use cases", "Understand limitations of AI-generated code"],
        },
        {
            "slug": "foundation-models",
            "title": "Foundation Models: The Infrastructure of Modern AI",
            "description": "What foundation models are, why they're revolutionary, and how the whole industry is built on them.",
            "level": "Intermediate", "category": "Models", "sequence_order": 30,
            "search_keywords": ["foundation models AI", "pre-trained models", "GPT-4 foundation model"],
            "learning_objectives": ["Define a foundation model", "Explain pre-training vs fine-tuning", "List the major foundation model families"],
        },
        {
            "slug": "ai-in-finance",
            "title": "AI in Finance: Trading, Risk, and Fraud Detection",
            "description": "How financial institutions use AI for algorithmic trading, credit scoring, and fraud detection.",
            "level": "Intermediate", "category": "Business", "sequence_order": 31,
            "search_keywords": ["AI finance", "algorithmic trading AI", "AI fraud detection banking"],
            "learning_objectives": ["Identify 4 financial AI applications", "Understand how anomaly detection works", "Explain explainability requirements in finance"],
        },
        {
            "slug": "ai-regulation",
            "title": "AI Regulation: Global Laws and Frameworks",
            "description": "The EU AI Act, US executive orders, and other regulatory frameworks shaping how AI can be used.",
            "level": "Intermediate", "category": "Safety", "sequence_order": 32,
            "search_keywords": ["AI regulation EU AI Act", "AI law", "AI governance policy"],
            "learning_objectives": ["Summarize the EU AI Act's risk tiers", "Understand US AI regulatory stance", "Explain why AI regulation is challenging"],
        },
        {
            "slug": "reinforcement-learning",
            "title": "Reinforcement Learning: AI That Learns by Doing",
            "description": "How RL trains AI through trial, error, and reward — the technique behind game-playing AI and robotics.",
            "level": "Intermediate", "category": "Foundations", "sequence_order": 33,
            "search_keywords": ["reinforcement learning AI", "RL agent reward", "AlphaGo reinforcement learning"],
            "learning_objectives": ["Define the agent-environment RL loop", "Explain reward shaping", "Name 2 major RL successes (games, robotics)"],
        },
        {
            "slug": "ai-content-detection",
            "title": "Detecting AI-Generated Content",
            "description": "The techniques used to identify AI-written text, deepfakes, and synthetic media — and their limitations.",
            "level": "Intermediate", "category": "Safety", "sequence_order": 34,
            "search_keywords": ["AI detection tools", "AI text detector", "deepfake detection"],
            "learning_objectives": ["Explain how AI detection tools work", "Understand why detection is an arms race", "Know the accuracy limitations of current detectors"],
        },
        {
            "slug": "ai-product-strategy",
            "title": "Building AI Products: Strategy and Moats",
            "description": "How companies build defensible AI products — data moats, distribution advantages, and UX differentiation.",
            "level": "Intermediate", "category": "Business", "sequence_order": 35,
            "search_keywords": ["AI product strategy", "AI startup moats", "building AI products"],
            "learning_objectives": ["Define what makes an AI product defensible", "Explain data network effects", "List 3 AI product failure modes"],
        },
        {
            "slug": "ai-memory-context",
            "title": "Context Windows and AI Memory",
            "description": "How LLM context windows work, why they matter, and emerging approaches to long-term AI memory.",
            "level": "Intermediate", "category": "Models", "sequence_order": 36,
            "search_keywords": ["LLM context window", "AI long context memory", "token limit GPT"],
            "learning_objectives": ["Explain what a context window is", "Understand token limits and their consequences", "Describe approaches to long-term AI memory"],
        },
        {
            "slug": "ai-voice-audio",
            "title": "AI Voice and Audio: Text-to-Speech and Beyond",
            "description": "How AI generates realistic speech, clones voices, and enables real-time audio translation.",
            "level": "Intermediate", "category": "Applications", "sequence_order": 37,
            "search_keywords": ["AI voice generation", "text to speech AI", "voice cloning AI"],
            "learning_objectives": ["Explain how neural TTS works", "Identify 3 legitimate AI voice use cases", "Understand voice cloning risks"],
        },
        {
            "slug": "open-source-ai",
            "title": "Open Source AI: Llama, Mistral, and the Open Ecosystem",
            "description": "The rise of open-source AI models and what their availability means for innovation, privacy, and safety.",
            "level": "Intermediate", "category": "Models", "sequence_order": 38,
            "search_keywords": ["open source AI models", "Llama Meta AI", "Mistral AI open source"],
            "learning_objectives": ["Name the major open-source AI models", "Understand the open vs closed model debate", "Explain the benefits and risks of open AI"],
        },
        {
            "slug": "ai-robotics",
            "title": "AI and Robotics: Physical Intelligence",
            "description": "How AI enables robots to navigate, manipulate objects, and learn physical tasks in the real world.",
            "level": "Intermediate", "category": "Applications", "sequence_order": 39,
            "search_keywords": ["AI robotics", "Boston Dynamics AI", "autonomous robots AI"],
            "learning_objectives": ["Explain embodied AI", "Describe the sim-to-real transfer challenge", "Identify 3 real-world robotics AI deployments"],
        },
        {
            "slug": "ai-search",
            "title": "AI Search: How LLMs Are Changing How We Find Information",
            "description": "How AI is transforming web search — from traditional index-based to conversational, generative answers.",
            "level": "Intermediate", "category": "Applications", "sequence_order": 40,
            "search_keywords": ["AI search engines", "Perplexity AI search", "Google AI overview"],
            "learning_objectives": ["Explain how AI search differs from traditional search", "Understand retrieval + generation in search", "Evaluate AI search accuracy risks"],
        },

        # ─── ADVANCED (seq 41–60) ─────────────────────────────────────────────
        {
            "slug": "rlhf",
            "title": "RLHF: Training AI to Be Helpful and Harmless",
            "description": "Reinforcement Learning from Human Feedback — the technique that made ChatGPT safe and useful.",
            "level": "Advanced", "category": "Models", "sequence_order": 41,
            "search_keywords": ["RLHF reinforcement learning human feedback", "AI alignment training", "InstructGPT RLHF"],
            "learning_objectives": ["Explain the RLHF pipeline step by step", "Describe what a reward model does", "Understand PPO in the RL context"],
        },
        {
            "slug": "ai-alignment",
            "title": "AI Alignment: The Hardest Problem in AI",
            "description": "The challenge of ensuring advanced AI systems pursue goals that are genuinely beneficial to humanity.",
            "level": "Advanced", "category": "Safety", "sequence_order": 42,
            "search_keywords": ["AI alignment problem", "AI safety research", "AGI alignment"],
            "learning_objectives": ["Define AI alignment and why it's hard", "Explain inner vs outer alignment", "Describe mesa-optimization"],
        },
        {
            "slug": "mixture-of-experts",
            "title": "Mixture of Experts: How AI Scales Efficiently",
            "description": "The MoE architecture powering models like GPT-4 and Mixtral — routing inputs to specialized sub-networks.",
            "level": "Advanced", "category": "Models", "sequence_order": 43,
            "search_keywords": ["mixture of experts AI", "MoE LLM architecture", "sparse model AI"],
            "learning_objectives": ["Explain the MoE routing mechanism", "Understand sparsity and efficiency gains", "Contrast MoE with dense models"],
        },
        {
            "slug": "ai-inference-optimization",
            "title": "Making AI Fast: Inference Optimization",
            "description": "Techniques like quantization, distillation, and speculative decoding that make large AI models practical to deploy.",
            "level": "Advanced", "category": "Models", "sequence_order": 44,
            "search_keywords": ["AI inference optimization", "model quantization", "LLM deployment speed"],
            "learning_objectives": ["Define quantization and its trade-offs", "Explain knowledge distillation", "Understand speculative decoding"],
        },
        {
            "slug": "ai-safety-red-teaming",
            "title": "Red-Teaming AI: Finding Failures Before They Happen",
            "description": "How AI labs stress-test models for harmful outputs, jailbreaks, and unexpected failure modes.",
            "level": "Advanced", "category": "Safety", "sequence_order": 45,
            "search_keywords": ["AI red teaming", "AI jailbreak safety", "adversarial AI testing"],
            "learning_objectives": ["Define AI red teaming", "Describe common jailbreak techniques", "Explain why safety evaluation is ongoing"],
        },
        {
            "slug": "constitutional-ai",
            "title": "Constitutional AI: Teaching AI Its Own Values",
            "description": "Anthropic's approach to AI alignment — training Claude to critique and revise itself using a set of principles.",
            "level": "Advanced", "category": "Safety", "sequence_order": 46,
            "search_keywords": ["constitutional AI Anthropic", "Claude AI safety", "AI self-critique alignment"],
            "learning_objectives": ["Explain Constitutional AI vs RLHF", "Describe the CAI training pipeline", "Evaluate the strengths and limitations of this approach"],
        },
        {
            "slug": "scaling-laws",
            "title": "Scaling Laws: Why Bigger Models Are Better (Usually)",
            "description": "The empirical relationships between model size, data, compute, and performance — and when scaling stops working.",
            "level": "Advanced", "category": "Models", "sequence_order": 47,
            "search_keywords": ["AI scaling laws", "Chinchilla scaling", "compute optimal training AI"],
            "learning_objectives": ["Explain the Chinchilla scaling law", "Understand compute-optimal training", "Describe when scaling laws break down"],
        },
        {
            "slug": "ai-interpretability",
            "title": "AI Interpretability: Understanding the Black Box",
            "description": "Mechanistic interpretability research — understanding what computations actually happen inside LLMs.",
            "level": "Advanced", "category": "Safety", "sequence_order": 48,
            "search_keywords": ["AI interpretability", "mechanistic interpretability", "explainable AI research"],
            "learning_objectives": ["Define mechanistic interpretability", "Explain superposition and polysemanticity", "Understand why interpretability matters for safety"],
        },
        {
            "slug": "multiagent-systems",
            "title": "Multi-Agent AI Systems: Networks of AI Working Together",
            "description": "How multiple AI agents collaborate, delegate tasks, and check each other's work to solve complex problems.",
            "level": "Advanced", "category": "Applications", "sequence_order": 49,
            "search_keywords": ["multi-agent AI systems", "LLM agent network", "AutoGen AI agents"],
            "learning_objectives": ["Describe a multi-agent architecture", "Explain orchestration vs sub-agent roles", "Identify failure modes in multi-agent systems"],
        },
        {
            "slug": "ai-economic-impact",
            "title": "The Economic Impact of AI: Jobs, Productivity, and Inequality",
            "description": "What economic research says about AI's effect on labor markets, productivity, and income distribution.",
            "level": "Advanced", "category": "Business", "sequence_order": 50,
            "search_keywords": ["AI economic impact jobs", "AI automation labor market", "AI productivity research"],
            "learning_objectives": ["Summarize key economic research on AI and jobs", "Distinguish augmentation from replacement", "Understand which job categories are most at risk"],
        },
        {
            "slug": "ai-diffusion-models",
            "title": "Diffusion Models: The Math Behind AI Image Generation",
            "description": "How diffusion models iteratively denoise random signals to generate photorealistic images from text.",
            "level": "Advanced", "category": "Models", "sequence_order": 51,
            "search_keywords": ["diffusion model AI", "stable diffusion architecture", "denoising score matching"],
            "learning_objectives": ["Explain the forward and reverse diffusion process", "Understand classifier-free guidance", "Compare diffusion to GANs"],
        },
        {
            "slug": "ai-training-infrastructure",
            "title": "The Infrastructure of AI: GPUs, TPUs, and Data Centers",
            "description": "The hardware, networking, and distributed training systems that make large AI models possible.",
            "level": "Advanced", "category": "Foundations", "sequence_order": 52,
            "search_keywords": ["AI training infrastructure GPU", "TPU AI training", "distributed AI training"],
            "learning_objectives": ["Explain why GPUs dominate AI training", "Describe data parallelism and model parallelism", "Understand the compute requirements of frontier models"],
        },
        {
            "slug": "ai-memory-architectures",
            "title": "Beyond Context Windows: Advanced AI Memory",
            "description": "External memory, episodic memory, and retrieval mechanisms that give AI systems persistent knowledge.",
            "level": "Advanced", "category": "Models", "sequence_order": 53,
            "search_keywords": ["AI long-term memory", "external memory AI", "retrieval memory LLM"],
            "learning_objectives": ["Contrast short-term vs long-term AI memory approaches", "Explain episodic memory in AI", "Understand retrieval-augmented memory systems"],
        },
        {
            "slug": "ai-data-curation",
            "title": "Data Curation: Why Training Data Quality Matters",
            "description": "How the quality, diversity, and curation of training data shapes model capabilities and failure modes.",
            "level": "Advanced", "category": "Models", "sequence_order": 54,
            "search_keywords": ["AI training data quality", "data curation LLM", "AI dataset contamination"],
            "learning_objectives": ["Explain why data quality > data quantity", "Describe deduplication and quality filtering", "Understand benchmark contamination risks"],
        },
        {
            "slug": "ai-copyright-ip",
            "title": "AI and Copyright: Who Owns What AI Creates?",
            "description": "The legal battles around AI training data, generated outputs, and intellectual property rights.",
            "level": "Advanced", "category": "Safety", "sequence_order": 55,
            "search_keywords": ["AI copyright law", "generative AI intellectual property", "AI training data lawsuits"],
            "learning_objectives": ["Understand the key legal questions around AI-generated content", "Explain the fair use debate in AI training", "Describe major ongoing AI copyright cases"],
        },
        {
            "slug": "ai-geopolitics",
            "title": "The AI Race: Geopolitics and National Competition",
            "description": "How the US, China, and EU are competing in AI — chip restrictions, research leadership, and strategic implications.",
            "level": "Advanced", "category": "Business", "sequence_order": 56,
            "search_keywords": ["AI geopolitics US China", "AI chip restrictions", "global AI race"],
            "learning_objectives": ["Map the major national AI strategies", "Understand chip export controls", "Identify AI's role in national security"],
        },
        {
            "slug": "ai-existential-risk",
            "title": "Existential Risk from AI: A Serious Analysis",
            "description": "The arguments for and against treating advanced AI as an existential risk — what researchers actually believe.",
            "level": "Advanced", "category": "Safety", "sequence_order": 57,
            "search_keywords": ["AI existential risk", "AI x-risk", "AGI risk research"],
            "learning_objectives": ["Summarize the main arguments for AI existential risk", "Explain the main counter-arguments", "Identify which researchers hold each view"],
        },
        {
            "slug": "ai-reasoning-models",
            "title": "AI Reasoning Models: o1, R1, and Chain-of-Thought",
            "description": "How models trained to reason step-by-step outperform standard LLMs on complex tasks.",
            "level": "Advanced", "category": "Models", "sequence_order": 58,
            "search_keywords": ["AI reasoning models o1", "chain of thought prompting", "DeepSeek R1 reasoning"],
            "learning_objectives": ["Define chain-of-thought and its variants", "Explain how o1-style training works", "Identify tasks where reasoning models excel"],
        },
        {
            "slug": "ai-world-models",
            "title": "World Models: AI That Simulates Reality",
            "description": "How AI systems learn internal models of the world to enable planning, prediction, and simulation.",
            "level": "Advanced", "category": "Models", "sequence_order": 59,
            "search_keywords": ["AI world model", "model-based RL AI", "Sora video model world model"],
            "learning_objectives": ["Define a world model in the AI sense", "Explain how world models enable planning", "Contrast model-based vs model-free RL"],
        },
        {
            "slug": "agi-timeline-debate",
            "title": "AGI Timelines: What Experts Actually Think",
            "description": "A rigorous look at when AGI might arrive, why predictions vary wildly, and what the evidence actually supports.",
            "level": "Advanced", "category": "Foundations", "sequence_order": 60,
            "search_keywords": ["AGI timeline predictions", "when will AGI arrive", "artificial general intelligence research"],
            "learning_objectives": ["Summarize the range of AGI timeline predictions", "Understand why expert opinions diverge", "Evaluate the key uncertainties in AGI forecasting"],
        },
    ]

    async with SessionLocal() as db:
        # Fetch existing slugs to avoid duplicates
        existing_result = await db.execute(select(AiTopicCurriculum.slug))
        existing_slugs = {row[0] for row in existing_result.fetchall()}

        new_count = 0
        for topic_data in TOPICS:
            if topic_data["slug"] in existing_slugs:
                continue
            topic = AiTopicCurriculum(**topic_data)
            db.add(topic)
            new_count += 1

        if new_count > 0:
            await db.commit()
            logger.info("Seeded %d new AI curriculum topics into ai_topic_curriculum.", new_count)
        else:
            logger.info("AI curriculum already up to date (%d topics).", len(existing_slugs))


async def init_db():
    """
    Run schema column checks and seed initial admin, app settings, and curriculum data.
    """
    await ensure_db_columns()
    await seed_admin_user()
    await seed_app_settings()
    await seed_curriculum()
    logger.info("Database initialization check complete.")
