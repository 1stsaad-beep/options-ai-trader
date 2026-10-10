plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.optionsaitrader.options_ai_trader"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.optionsaitrader.options_ai_trader"
        if (System.getenv("OAT_PREVIEW_BUILD") == "true") applicationIdSuffix = ".v1preview"
        manifestPlaceholders["oatLabel"] = if (System.getenv("OAT_PREVIEW_BUILD") == "true") "Options AI Trader V1 Preview" else "Options AI Trader"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // Private development keys come only from the environment / CI Secrets.
    // Missing signing secrets produce an explicitly unsigned CI artifact.
    val privateKeyPath = System.getenv("OAT_KEYSTORE_PATH")
    val unsignedBuild = System.getenv("OAT_UNSIGNED_BUILD") == "true"
    if (!privateKeyPath.isNullOrBlank()) {
        signingConfigs.create("privateDevelopment") {
            storeFile = file(privateKeyPath)
            storePassword = System.getenv("OAT_KEYSTORE_PASSWORD") ?: error("Missing keystore password")
            keyAlias = System.getenv("OAT_KEY_ALIAS") ?: error("Missing signing alias")
            keyPassword = System.getenv("OAT_KEY_PASSWORD") ?: error("Missing key password")
        }
    }
    buildTypes {
        debug {
            if (unsignedBuild) signingConfig = null
            else if (!privateKeyPath.isNullOrBlank()) signingConfig = signingConfigs.getByName("privateDevelopment")
            // Local flutter run retains the SDK development key outside Git.
        }
        release {
            signingConfig = if (!unsignedBuild && !privateKeyPath.isNullOrBlank())
                signingConfigs.getByName("privateDevelopment") else null
        }
    }

}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
