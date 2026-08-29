//
//  SceneDelegate.swift
//  SomacuraCapture
//
//  Created by Thomas Amosson on 2026.08.28.
//

import SwiftUI
import UIKit

@MainActor
class SceneDelegate: UIResponder, UIWindowSceneDelegate {

    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene: windowScene)
        do {
            let runtime = try CaptureRuntime.live()
            let model = CaptureAppModel(runtime: runtime)
            window.rootViewController = UIHostingController(
                rootView: CaptureRootView(model: model)
            )
        } catch {
            window.rootViewController = UIHostingController(
                rootView: ConfigurationFailureView(message: error.localizedDescription)
                    .preferredColorScheme(.dark)
            )
        }
        self.window = window
        window.makeKeyAndVisible()
    }

}
